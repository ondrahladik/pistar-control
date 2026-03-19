import json
import threading
import time
from typing import Any, Dict, Optional
from urllib import error, parse, request

from api.api_client import ApiClient, ApiClientError
from core.app_logging import get_logger
from core.config import ConfigStore
from core.state import (
    get_state_snapshot,
    get_state_version,
    notify_state_change,
    update_state,
    wait_for_state_change_since,
)

logger = get_logger("app.telegram")


class TelegramBotService:
    def __init__(self, config_store: ConfigStore) -> None:
        self._config_store = config_store
        self._api_client = ApiClient(config_store)
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_rendered_text = ""
        self._last_rendered_markup = ""
        self._last_edit_attempt_at = 0.0
        self._last_readiness_state: Optional[str] = None
        self._last_seen_version = get_state_version()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run,
            name="telegram-bot",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)

    def request_dashboard_refresh(self) -> None:
        notify_state_change()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._config_store.reload()
            telegram_config = self._config_store.get_telegram_config()
            readiness_reason = _get_readiness_reason(telegram_config)
            if readiness_reason is not None:
                if self._last_readiness_state != readiness_reason:
                    logger.info("Bot idle: %s", readiness_reason)
                    self._last_readiness_state = readiness_reason
                self._last_seen_version = wait_for_state_change_since(self._last_seen_version, 2.0)
                continue

            try:
                if self._last_readiness_state != "ready":
                    logger.info("Bot ready, starting polling loop")
                    self._last_readiness_state = "ready"
                self._ensure_dashboard_message(telegram_config)
                self._maybe_update_dashboard(telegram_config, force=False)
                self._poll_updates(telegram_config)
                self._maybe_update_dashboard(telegram_config, force=False)
                self._last_seen_version = wait_for_state_change_since(self._last_seen_version, 0.02)
            except Exception as exc:
                logger.error("Bot loop error: %s: %s", type(exc).__name__, exc)
                self._last_seen_version = wait_for_state_change_since(self._last_seen_version, 2.0)

    def _ensure_dashboard_message(self, telegram_config: Dict[str, str]) -> None:
        snapshot = get_state_snapshot()
        message_id = snapshot.get("telegram_message_id")
        if isinstance(message_id, int):
            self._maybe_update_dashboard(telegram_config, force=False)
            return

        target_chat_id = _resolve_chat_id(telegram_config, snapshot)
        if not target_chat_id:
            return

        logger.info("Creating dashboard message")
        response = self._call_telegram(
            telegram_config=telegram_config,
            method_name="sendMessage",
            payload={
                "chat_id": target_chat_id,
                "text": self._render_dashboard_text(),
                "reply_markup": self._render_reply_markup(),
                **_thread_payload(telegram_config, snapshot),
            },
        )
        result = response.get("result", {})
        if isinstance(result, dict) and isinstance(result.get("message_id"), int):
            update_state(telegram_message_id=result["message_id"])
            self._last_rendered_text = self._render_dashboard_text()
            self._last_rendered_markup = self._render_reply_markup()
            logger.info("Dashboard message created with id %s", result["message_id"])

    def _poll_updates(self, telegram_config: Dict[str, str]) -> None:
        snapshot = get_state_snapshot()
        offset = snapshot.get("telegram_update_offset") or 0
        response = self._call_telegram(
            telegram_config=telegram_config,
            method_name="getUpdates",
            payload={
                "timeout": 0,
                "offset": offset,
            },
        )

        updates = response.get("result", [])
        if not isinstance(updates, list):
            return

        highest_offset = offset
        for item in updates:
            if not isinstance(item, dict):
                continue
            update_id = item.get("update_id")
            if isinstance(update_id, int):
                highest_offset = max(highest_offset, update_id + 1)
            self._handle_update(telegram_config, item)

        if highest_offset != offset:
            update_state(telegram_update_offset=highest_offset)

    def _handle_update(self, telegram_config: Dict[str, str], update_payload: Dict[str, Any]) -> None:
        callback_query = update_payload.get("callback_query")
        if isinstance(callback_query, dict):
            self._handle_callback_query(telegram_config, callback_query)
            return

        message = update_payload.get("message")
        if not isinstance(message, dict):
            return

        text = message.get("text")
        if not isinstance(text, str) or not text.startswith("/"):
            return

        chat = message.get("chat", {})
        message_id = message.get("message_id")
        chat_id = str(chat.get("id", ""))
        snapshot = get_state_snapshot()
        if not self._matches_target_chat(telegram_config, snapshot, chat_id):
            return
        if not _matches_thread(telegram_config, snapshot, message.get("message_thread_id")):
            return

        self._remember_chat_binding(chat_id, message.get("message_thread_id"))

        command = text.split("@", 1)[0].split()[0].lstrip("/").lower()
        aliases = self._config_store.get_telegram_aliases()
        target_network = aliases.get(command)
        if target_network:
            try:
                logger.info("Switching network via command /%s -> %s", command, target_network)
                self._api_client.switch_network(target_network)
            except ApiClientError as exc:
                logger.warning("Telegram command '/%s' failed: %s", command, exc)
        else:
            logger.info("Ignoring unknown command /%s", command)
        self._delete_message(telegram_config, chat_id=chat_id, message_id=message_id)
        self._maybe_update_dashboard(telegram_config, force=True)

    def _handle_callback_query(self, telegram_config: Dict[str, str], callback_query: Dict[str, Any]) -> None:
        callback_id = callback_query.get("id")
        payload = callback_query.get("data", "")
        message = callback_query.get("message", {})
        chat = message.get("chat", {}) if isinstance(message, dict) else {}
        chat_id = str(chat.get("id", ""))
        snapshot = get_state_snapshot()

        if not self._matches_target_chat(telegram_config, snapshot, chat_id):
            return
        if not _matches_thread(
            telegram_config,
            snapshot,
            message.get("message_thread_id") if isinstance(message, dict) else None,
        ):
            return

        self._remember_chat_binding(
            chat_id,
            message.get("message_thread_id") if isinstance(message, dict) else None,
        )

        if isinstance(payload, str) and payload.startswith("switch:"):
            command = payload.split(":", 1)[1].strip().lower()
            aliases = self._config_store.get_telegram_aliases()
            target_network = aliases.get(command)
            if target_network:
                try:
                    logger.info("Switching network via button /%s -> %s", command, target_network)
                    self._api_client.switch_network(target_network)
                    network_label = self._config_store.get_network_alias(target_network)
                    self._answer_callback_query(telegram_config, callback_id, f"Prepnuto na {network_label}")
                except ApiClientError as exc:
                    logger.warning("Telegram button '/%s' failed: %s", command, exc)
                    self._answer_callback_query(telegram_config, callback_id, "Prepnuti selhalo")
            else:
                self._answer_callback_query(telegram_config, callback_id, "Neznamy prikaz")
            self._maybe_update_dashboard(telegram_config, force=True)
            return

        self._answer_callback_query(telegram_config, callback_id, "Bez akce")

    def _answer_callback_query(
        self,
        telegram_config: Dict[str, str],
        callback_id: Any,
        text: str,
    ) -> None:
        if not isinstance(callback_id, str):
            return
        try:
            self._call_telegram(
                telegram_config=telegram_config,
                method_name="answerCallbackQuery",
                payload={
                    "callback_query_id": callback_id,
                    "text": text,
                },
            )
        except TelegramApiError as exc:
            logger.warning("answerCallbackQuery failed: %s", exc)

    def _delete_message(self, telegram_config: Dict[str, str], chat_id: str, message_id: Any) -> None:
        if not isinstance(message_id, int):
            return

        try:
            self._call_telegram(
                telegram_config=telegram_config,
                method_name="deleteMessage",
                payload={
                    "chat_id": chat_id,
                    "message_id": message_id,
                },
            )
        except TelegramApiError as exc:
            logger.warning("deleteMessage failed: %s", exc)

    def _maybe_update_dashboard(self, telegram_config: Dict[str, str], force: bool) -> None:
        now = time.monotonic()
        text = self._render_dashboard_text()
        markup = self._render_reply_markup()
        if not force and text == self._last_rendered_text and markup == self._last_rendered_markup:
            return

        snapshot = get_state_snapshot()
        message_id = snapshot.get("telegram_message_id")
        target_chat_id = _resolve_chat_id(telegram_config, snapshot)
        if not isinstance(message_id, int):
            return
        if not target_chat_id:
            return

        try:
            self._call_telegram(
                telegram_config=telegram_config,
                method_name="editMessageText",
                payload={
                    "chat_id": target_chat_id,
                    "message_id": message_id,
                    "text": text,
                    "reply_markup": markup,
                },
            )
            self._last_rendered_text = text
            self._last_rendered_markup = markup
            self._last_edit_attempt_at = now
        except TelegramApiError as exc:
            self._last_edit_attempt_at = now
            if "message is not modified" in str(exc).lower():
                self._last_rendered_text = text
                self._last_rendered_markup = markup
                return
            if "message to edit not found" in str(exc).lower():
                update_state(telegram_message_id=None)
            logger.warning("editMessageText failed: %s", exc)

    @staticmethod
    def _matches_target_chat(
        telegram_config: Dict[str, str],
        snapshot: Dict[str, Any],
        chat_id: str,
    ) -> bool:
        target_chat_id = _resolve_chat_id(telegram_config, snapshot)
        if target_chat_id:
            return chat_id == target_chat_id

        return bool(chat_id)

    @staticmethod
    def _remember_chat_binding(chat_id: str, thread_id: Any) -> None:
        updates: Dict[str, Any] = {}
        snapshot = get_state_snapshot()
        if chat_id and snapshot.get("telegram_chat_id") != chat_id:
            updates["telegram_chat_id"] = chat_id

        normalized_thread_id = str(thread_id) if thread_id is not None else ""
        if snapshot.get("telegram_thread_id") != normalized_thread_id:
            updates["telegram_thread_id"] = normalized_thread_id

        if updates:
            update_state(**updates)

    def _render_dashboard_text(self) -> str:
        self._config_store.reload()
        snapshot = get_state_snapshot()
        current_network = snapshot.get("current_network")
        current_network_label = (
            self._config_store.get_network_alias(current_network)
            if isinstance(current_network, str) and current_network
            else "Neznámá"
        )
        active_call = snapshot.get("active_call")
        if isinstance(active_call, dict):
            active_call_line = (
                f"🗣️ {active_call.get('callsign', '?')}\n🎯 TG {active_call.get('talkgroup', '?')}"
            )
        else:
            active_call_line = "🗣️ ---\n🎯 ---"

        return "\n".join(
            [
                "⠀",
                f"🌐 {current_network_label}",
                "",
                active_call_line,
                "",
                f"⏱️ {snapshot.get('last_update_at') or '--:--:--'}",
            ]
        )

    def _render_reply_markup(self) -> str:
        aliases = self._config_store.get_telegram_aliases()
        commands = sorted(aliases.keys())
        rows = []
        current_row = []

        for command in commands:
            current_row.append({
                "text": f"/{command}",
                "callback_data": f"switch:{command}",
            })
            if len(current_row) == 2:
                rows.append(current_row)
                current_row = []

        if current_row:
            rows.append(current_row)

        return json.dumps({"inline_keyboard": rows}, ensure_ascii=False, separators=(",", ":"))

    def _call_telegram(
        self,
        telegram_config: Dict[str, str],
        method_name: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        encoded_payload = parse.urlencode(
            {key: str(value) for key, value in payload.items()}
        ).encode("utf-8")
        last_error: Optional[Exception] = None

        for attempt in range(3):
            http_request = request.Request(
                url=(
                    f"https://api.telegram.org/bot"
                    f"{telegram_config['bot_token']}/{method_name}"
                ),
                data=encoded_payload,
                method="POST",
            )

            try:
                with request.urlopen(http_request, timeout=30) as response:
                    response_payload = json.loads(response.read().decode("utf-8"))
                break
            except error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="ignore")
                raise TelegramApiError(body or f"HTTP {exc.code}") from exc
            except (error.URLError, ConnectionResetError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt == 2:
                    raise TelegramApiError(str(exc)) from exc
                time.sleep(0.6 * (attempt + 1))
        else:
            raise TelegramApiError(str(last_error or "Unknown Telegram transport error"))

        if not response_payload.get("ok"):
            raise TelegramApiError(str(response_payload.get("description", "Unknown Telegram API error")))

        return response_payload


class TelegramApiError(Exception):
    pass


def _is_bot_ready(telegram_config: Dict[str, str]) -> bool:
    return _get_readiness_reason(telegram_config) is None


def _get_readiness_reason(telegram_config: Dict[str, str]) -> Optional[str]:
    enabled = telegram_config.get("enabled", "false").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return "disabled in config"
    if not telegram_config.get("bot_token"):
        return "missing bot token"
    return None


def _thread_payload(telegram_config: Dict[str, str], snapshot: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    thread_id = _resolve_thread_id(telegram_config, snapshot or get_state_snapshot())
    if not thread_id:
        return {}
    return {"message_thread_id": thread_id}


def _matches_thread(
    telegram_config: Dict[str, str],
    snapshot: Optional[Dict[str, Any]],
    message_thread_id: Any,
) -> bool:
    configured_thread_id = _resolve_thread_id(telegram_config, snapshot or get_state_snapshot())
    if not configured_thread_id:
        return True
    return str(message_thread_id or "") == configured_thread_id


def _resolve_chat_id(telegram_config: Dict[str, str], snapshot: Dict[str, Any]) -> str:
    configured_chat_id = telegram_config.get("chat_id", "").strip()
    if configured_chat_id:
        return configured_chat_id

    persisted_chat_id = snapshot.get("telegram_chat_id")
    return str(persisted_chat_id).strip() if persisted_chat_id is not None else ""


def _resolve_thread_id(telegram_config: Dict[str, str], snapshot: Dict[str, Any]) -> str:
    configured_thread_id = telegram_config.get("thread_id", "").strip()
    if configured_thread_id:
        return configured_thread_id

    persisted_thread_id = snapshot.get("telegram_thread_id")
    return str(persisted_thread_id).strip() if persisted_thread_id is not None else ""
