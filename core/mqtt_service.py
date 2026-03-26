import json
import socket
import threading
import time
from typing import Any, Dict, Optional, Tuple

from core.app_logging import get_logger
from core.config import ConfigStore
from core.state import get_state_snapshot, get_state_version, wait_for_state_change_since
from api.api_client import ApiClient, ApiClientError

logger = get_logger("app.mqtt")


class MqttPublisherService:
    def __init__(self, config_store: ConfigStore) -> None:
        self._config_store = config_store
        self._api_client = ApiClient(config_store)
        self._publish_thread: Optional[threading.Thread] = None
        self._subscribe_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_seen_version = get_state_version()
        self._last_published_payload = ""
        self._last_publish_signature = ""
        self._last_subscribe_signature = ""

    def start(self) -> None:
        if not self._publish_thread or not self._publish_thread.is_alive():
            self._publish_thread = threading.Thread(
                target=self._run_publisher,
                name="mqtt-publisher",
                daemon=True,
            )
            self._publish_thread.start()

        if not self._subscribe_thread or not self._subscribe_thread.is_alive():
            self._subscribe_thread = threading.Thread(
                target=self._run_subscriber,
                name="mqtt-subscriber",
                daemon=True,
            )
            self._subscribe_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._publish_thread:
            self._publish_thread.join(timeout=2)
        if self._subscribe_thread:
            self._subscribe_thread.join(timeout=2)

    def _run_publisher(self) -> None:
        while not self._stop_event.is_set():
            self._config_store.reload()
            mqtt_config = self._config_store.get_mqtt_config()
            readiness_reason = _get_publish_readiness_reason(mqtt_config)
            if readiness_reason is not None:
                if self._last_publish_signature != readiness_reason:
                    logger.info("MQTT publisher idle: %s", readiness_reason)
                    self._last_publish_signature = readiness_reason
                self._last_seen_version = wait_for_state_change_since(self._last_seen_version, 2.0)
                continue

            config_signature = _publish_config_signature(mqtt_config)
            payload = _build_payload(get_state_snapshot(), self._config_store)

            if payload != self._last_published_payload or config_signature != self._last_publish_signature:
                try:
                    _publish_message(mqtt_config, payload)
                    self._last_published_payload = payload
                    self._last_publish_signature = config_signature
                    logger.info(
                        "Published state to MQTT topic %s on %s:%s",
                        mqtt_config["topic_pub"],
                        mqtt_config["server"],
                        mqtt_config["port"],
                    )
                except Exception as exc:
                    logger.warning("MQTT publish failed: %s", exc)

            self._last_seen_version = wait_for_state_change_since(self._last_seen_version, 2.0)

    def _run_subscriber(self) -> None:
        while not self._stop_event.is_set():
            self._config_store.reload()
            mqtt_config = self._config_store.get_mqtt_config()
            readiness_reason = _get_subscribe_readiness_reason(mqtt_config)
            if readiness_reason is not None:
                if self._last_subscribe_signature != readiness_reason:
                    logger.info("MQTT subscriber idle: %s", readiness_reason)
                    self._last_subscribe_signature = readiness_reason
                self._stop_event.wait(2.0)
                continue

            config_signature = _subscribe_config_signature(mqtt_config)
            if config_signature != self._last_subscribe_signature:
                logger.info(
                    "MQTT subscriber connecting to %s:%s topic %s",
                    mqtt_config["server"],
                    mqtt_config["port"],
                    mqtt_config["topic_sub"],
                )
                self._last_subscribe_signature = config_signature

            try:
                self._listen_for_commands(mqtt_config)
            except Exception as exc:
                if self._stop_event.is_set():
                    return
                logger.warning("MQTT subscribe failed: %s", exc)
                self._stop_event.wait(2.0)

    def _listen_for_commands(self, mqtt_config: Dict[str, str]) -> None:
        server = mqtt_config["server"].strip()
        port = int(mqtt_config.get("port", "1883").strip() or "1883")
        username = mqtt_config.get("username", "").strip()
        password = mqtt_config.get("password", "")
        topic = mqtt_config["topic_sub"].strip()
        keepalive_seconds = 30

        with socket.create_connection((server, port), timeout=10) as connection:
            connection.settimeout(1.0)
            _send_connect_packet(
                connection,
                username=username,
                password=password,
                keepalive_seconds=keepalive_seconds,
                client_role="sub",
            )
            _read_connack(connection)
            _send_subscribe_packet(connection, topic=topic)
            _read_suback(connection)

            last_ping_at = time.monotonic()
            while not self._stop_event.is_set():
                try:
                    packet_type, payload = _read_packet(connection)
                except socket.timeout:
                    if time.monotonic() - last_ping_at >= keepalive_seconds / 2:
                        _send_ping_request(connection)
                        last_ping_at = time.monotonic()
                    continue

                if packet_type == _MQTT_PACKET_TYPE_PUBLISH:
                    message_topic, message_payload = _decode_publish_packet(payload)
                    if message_topic == topic:
                        self._handle_command(message_payload)
                elif packet_type == _MQTT_PACKET_TYPE_PINGRESP:
                    last_ping_at = time.monotonic()

    def _handle_command(self, raw_payload: str) -> None:
        command = raw_payload.strip().lower()
        if not command:
            return

        aliases = self._config_store.get_telegram_aliases()
        aliases.update({network.lower(): network for network in self._config_store.list_networks()})
        target_network = aliases.get(command)
        if not target_network:
            logger.info("Ignoring unknown MQTT command '%s'", raw_payload.strip())
            return

        try:
            logger.info("Switching network via MQTT command '%s' -> %s", command, target_network)
            self._api_client.switch_network(target_network)
        except ApiClientError as exc:
            logger.warning("MQTT command '%s' failed: %s", command, exc)


_MQTT_PACKET_TYPE_PUBLISH = 3
_MQTT_PACKET_TYPE_SUBACK = 9
_MQTT_PACKET_TYPE_PINGRESP = 13


def _build_payload(snapshot: Dict[str, Any], config_store: ConfigStore) -> str:
    active_call = snapshot.get("active_call")
    callsign = None
    talkgroup = None
    current_network = snapshot.get("current_network")

    if isinstance(active_call, dict):
        callsign = active_call.get("callsign")
        talkgroup = active_call.get("talkgroup")

    payload = {
        "network": (
            config_store.get_network_alias(current_network)
            if isinstance(current_network, str) and current_network
            else None
        ),
        "callsign": callsign,
        "talkgroup": talkgroup,
        "time": snapshot.get("last_update_at"),
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _publish_config_signature(mqtt_config: Dict[str, str]) -> str:
    signature_payload = {
        "server": mqtt_config.get("server", ""),
        "port": mqtt_config.get("port", ""),
        "username": mqtt_config.get("username", ""),
        "password": mqtt_config.get("password", ""),
        "topic_pub": mqtt_config.get("topic_pub", ""),
    }
    return json.dumps(signature_payload, ensure_ascii=False, sort_keys=True)


def _subscribe_config_signature(mqtt_config: Dict[str, str]) -> str:
    signature_payload = {
        "server": mqtt_config.get("server", ""),
        "port": mqtt_config.get("port", ""),
        "username": mqtt_config.get("username", ""),
        "password": mqtt_config.get("password", ""),
        "topic_sub": mqtt_config.get("topic_sub", ""),
    }
    return json.dumps(signature_payload, ensure_ascii=False, sort_keys=True)


def _get_publish_readiness_reason(mqtt_config: Dict[str, str]) -> Optional[str]:
    common_reason = _get_common_readiness_reason(mqtt_config)
    if common_reason is not None:
        return common_reason
    if not mqtt_config.get("topic_pub", "").strip():
        return "missing publish topic"
    return None


def _get_subscribe_readiness_reason(mqtt_config: Dict[str, str]) -> Optional[str]:
    common_reason = _get_common_readiness_reason(mqtt_config)
    if common_reason is not None:
        return common_reason
    if not mqtt_config.get("topic_sub", "").strip():
        return "missing subscribe topic"
    return None


def _get_common_readiness_reason(mqtt_config: Dict[str, str]) -> Optional[str]:
    enabled = mqtt_config.get("enabled", "false").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return "disabled in config"
    if not mqtt_config.get("server", "").strip():
        return "missing server"
    try:
        port = int(mqtt_config.get("port", "1883"))
    except ValueError:
        return "invalid port"
    if port <= 0 or port > 65535:
        return "invalid port"
    return None


def _publish_message(mqtt_config: Dict[str, str], payload: str) -> None:
    server = mqtt_config["server"].strip()
    port = int(mqtt_config.get("port", "1883").strip() or "1883")
    topic = mqtt_config["topic_pub"].strip()
    username = mqtt_config.get("username", "").strip()
    password = mqtt_config.get("password", "")

    with socket.create_connection((server, port), timeout=10) as connection:
        connection.settimeout(10)
        _send_connect_packet(connection, username=username, password=password, client_role="pub")
        _read_connack(connection)
        _send_publish_packet(connection, topic=topic, payload=payload)
        connection.sendall(b"\xe0\x00")


def _send_connect_packet(
    connection: socket.socket,
    username: str,
    password: str,
    keepalive_seconds: int = 30,
    client_role: str = "app",
) -> None:
    client_id = _build_client_id(client_role)
    connect_flags = 0x02
    payload = _encode_utf8(client_id)

    if username:
        connect_flags |= 0x80
        payload += _encode_utf8(username)
        if password:
            connect_flags |= 0x40
            payload += _encode_utf8(password)

    variable_header = (
        _encode_utf8("MQTT")
        + b"\x04"
        + bytes([connect_flags])
        + keepalive_seconds.to_bytes(2, "big")
    )
    packet = b"\x10" + _encode_remaining_length(len(variable_header) + len(payload)) + variable_header + payload
    connection.sendall(packet)


def _build_client_id(client_role: str) -> str:
    hostname = socket.gethostname()
    client_id = f"pc-{client_role}-{hostname}"
    return client_id[:23]


def _send_publish_packet(connection: socket.socket, topic: str, payload: str) -> None:
    topic_bytes = _encode_utf8(topic)
    payload_bytes = payload.encode("utf-8")
    variable_payload = topic_bytes + payload_bytes
    packet = b"\x30" + _encode_remaining_length(len(variable_payload)) + variable_payload
    connection.sendall(packet)


def _send_subscribe_packet(connection: socket.socket, topic: str) -> None:
    packet_id = (1).to_bytes(2, "big")
    payload = _encode_utf8(topic) + b"\x00"
    remaining_payload = packet_id + payload
    packet = b"\x82" + _encode_remaining_length(len(remaining_payload)) + remaining_payload
    connection.sendall(packet)


def _send_ping_request(connection: socket.socket) -> None:
    connection.sendall(b"\xc0\x00")


def _read_connack(connection: socket.socket) -> None:
    packet_type, payload = _read_packet(connection)
    if packet_type != 2:
        raise RuntimeError("Invalid MQTT CONNACK header")
    if len(payload) != 2:
        raise RuntimeError("Invalid MQTT CONNACK payload")

    return_code = payload[1]
    if return_code != 0:
        raise RuntimeError(f"MQTT broker rejected connection with code {return_code}")


def _read_suback(connection: socket.socket) -> None:
    packet_type, payload = _read_packet(connection)
    if packet_type != _MQTT_PACKET_TYPE_SUBACK:
        raise RuntimeError("Invalid MQTT SUBACK header")
    if len(payload) < 3:
        raise RuntimeError("Invalid MQTT SUBACK payload")
    if payload[-1] == 0x80:
        raise RuntimeError("MQTT broker rejected subscription")


def _read_packet(connection: socket.socket) -> Tuple[int, bytes]:
    fixed_header = _read_exact(connection, 1)[0]
    remaining_length = _read_remaining_length(connection)
    payload = _read_exact(connection, remaining_length)
    packet_type = fixed_header >> 4
    return packet_type, payload


def _decode_publish_packet(payload: bytes) -> Tuple[str, str]:
    if len(payload) < 2:
        raise RuntimeError("Invalid MQTT publish payload")

    topic_length = int.from_bytes(payload[:2], "big")
    if len(payload) < 2 + topic_length:
        raise RuntimeError("Invalid MQTT publish topic")

    topic = payload[2:2 + topic_length].decode("utf-8")
    message = payload[2 + topic_length :].decode("utf-8", errors="ignore")
    return topic, message


def _encode_utf8(value: str) -> bytes:
    return _encode_utf8_bytes(value.encode("utf-8"))


def _encode_utf8_bytes(value: bytes) -> bytes:
    return len(value).to_bytes(2, "big") + value


def _encode_remaining_length(length: int) -> bytes:
    encoded = bytearray()
    while True:
        digit = length % 128
        length //= 128
        if length > 0:
            digit |= 0x80
        encoded.append(digit)
        if length == 0:
            return bytes(encoded)


def _read_remaining_length(connection: socket.socket) -> int:
    multiplier = 1
    value = 0
    while True:
        encoded_byte = _read_exact(connection, 1)[0]
        value += (encoded_byte & 127) * multiplier
        if (encoded_byte & 128) == 0:
            return value
        multiplier *= 128
        if multiplier > 128 * 128 * 128:
            raise RuntimeError("Invalid MQTT remaining length")


def _read_exact(connection: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = connection.recv(size - len(chunks))
        if not chunk:
            raise RuntimeError("Unexpected MQTT socket close")
        chunks.extend(chunk)
    return bytes(chunks)
