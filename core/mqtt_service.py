import json
import socket
import threading
from typing import Any, Dict, Optional

from core.app_logging import get_logger
from core.config import ConfigStore
from core.state import get_state_snapshot, get_state_version, wait_for_state_change_since

logger = get_logger("app.mqtt")


class MqttPublisherService:
    def __init__(self, config_store: ConfigStore) -> None:
        self._config_store = config_store
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_seen_version = get_state_version()
        self._last_published_payload = ""
        self._last_config_signature = ""

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run,
            name="mqtt-publisher",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._config_store.reload()
            mqtt_config = self._config_store.get_mqtt_config()
            readiness_reason = _get_readiness_reason(mqtt_config)
            if readiness_reason is not None:
                if self._last_config_signature != readiness_reason:
                    logger.info("MQTT idle: %s", readiness_reason)
                    self._last_config_signature = readiness_reason
                self._last_seen_version = wait_for_state_change_since(self._last_seen_version, 2.0)
                continue

            config_signature = _config_signature(mqtt_config)
            payload = _build_payload(get_state_snapshot(), self._config_store)

            if (
                payload != self._last_published_payload
                or config_signature != self._last_config_signature
            ):
                try:
                    _publish_message(mqtt_config, payload)
                    self._last_published_payload = payload
                    self._last_config_signature = config_signature
                    logger.info(
                        "Published state to MQTT topic %s on %s:%s",
                        mqtt_config["topic"],
                        mqtt_config["server"],
                        mqtt_config["port"],
                    )
                except Exception as exc:
                    logger.warning("MQTT publish failed: %s", exc)

            self._last_seen_version = wait_for_state_change_since(self._last_seen_version, 2.0)


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


def _config_signature(mqtt_config: Dict[str, str]) -> str:
    signature_payload = {
        "server": mqtt_config.get("server", ""),
        "port": mqtt_config.get("port", ""),
        "username": mqtt_config.get("username", ""),
        "password": mqtt_config.get("password", ""),
        "topic": mqtt_config.get("topic", ""),
    }
    return json.dumps(signature_payload, ensure_ascii=False, sort_keys=True)


def _get_readiness_reason(mqtt_config: Dict[str, str]) -> Optional[str]:
    enabled = mqtt_config.get("enabled", "false").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return "disabled in config"
    if not mqtt_config.get("server", "").strip():
        return "missing server"
    if not mqtt_config.get("topic", "").strip():
        return "missing topic"
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
    topic = mqtt_config["topic"].strip()
    username = mqtt_config.get("username", "").strip()
    password = mqtt_config.get("password", "")

    with socket.create_connection((server, port), timeout=10) as connection:
        connection.settimeout(10)
        _send_connect_packet(connection, username=username, password=password)
        _read_connack(connection)
        _send_publish_packet(connection, topic=topic, payload=payload)
        connection.sendall(b"\xe0\x00")


def _send_connect_packet(connection: socket.socket, username: str, password: str) -> None:
    client_id = f"pistar-control-{socket.gethostname()}".encode("utf-8")[:23]
    connect_flags = 0x02
    payload = _encode_utf8_bytes(client_id)

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
        + (30).to_bytes(2, "big")
    )
    packet = b"\x10" + _encode_remaining_length(len(variable_header) + len(payload)) + variable_header + payload
    connection.sendall(packet)


def _send_publish_packet(connection: socket.socket, topic: str, payload: str) -> None:
    topic_bytes = _encode_utf8(topic)
    payload_bytes = payload.encode("utf-8")
    variable_payload = topic_bytes + payload_bytes
    packet = b"\x30" + _encode_remaining_length(len(variable_payload)) + variable_payload
    connection.sendall(packet)


def _read_connack(connection: socket.socket) -> None:
    packet_type = connection.recv(1)
    if packet_type != b"\x20":
        raise RuntimeError("Invalid MQTT CONNACK header")

    remaining_length = _read_remaining_length(connection)
    payload = _read_exact(connection, remaining_length)
    if len(payload) != 2:
        raise RuntimeError("Invalid MQTT CONNACK payload")

    return_code = payload[1]
    if return_code != 0:
        raise RuntimeError(f"MQTT broker rejected connection with code {return_code}")


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
