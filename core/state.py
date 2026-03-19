import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


lock = threading.Lock()
change_event = threading.Event()
_state_path: Optional[Path] = None
_persistent_keys = {
    "current_network",
    "telegram_message_id",
    "telegram_update_offset",
}

state: Dict[str, Any] = {
    "current_network": None,
    "active_call": None,
    "telegram_message_id": None,
    "telegram_update_offset": 0,
    "last_update_at": None,
}


def init_state(state_path: Path) -> None:
    global _state_path
    _state_path = state_path
    _state_path.parent.mkdir(parents=True, exist_ok=True)
    persisted_state = _load_from_disk(_state_path)
    with lock:
        state.update(persisted_state)
        _touch_locked()


def get_state_snapshot() -> Dict[str, Any]:
    with lock:
        active_call = state.get("active_call")
        return {
            "current_network": state.get("current_network"),
            "active_call": dict(active_call) if isinstance(active_call, dict) else None,
            "telegram_message_id": state.get("telegram_message_id"),
            "telegram_update_offset": state.get("telegram_update_offset", 0),
            "last_update_at": state.get("last_update_at"),
        }


def update_state(**updates: Any) -> Dict[str, Any]:
    with lock:
        persistent_changed = False
        state_changed = False

        for key, value in updates.items():
            if state.get(key) == value:
                continue
            state[key] = value
            state_changed = True
            if key in _persistent_keys:
                persistent_changed = True

        if not state_changed:
            return _snapshot_locked()

        _touch_locked()
        if persistent_changed:
            _save_locked()
        change_event.set()
        return _snapshot_locked()


def set_active_call(callsign: str, talkgroup: str) -> Dict[str, Any]:
    return update_state(
        active_call={
            "callsign": callsign,
            "talkgroup": talkgroup,
        }
    )


def clear_active_call() -> Dict[str, Any]:
    return update_state(active_call=None)


def persist_runtime_state() -> None:
    with lock:
        _save_locked()


def wait_for_state_change(timeout: float) -> bool:
    changed = change_event.wait(timeout)
    if changed:
        change_event.clear()
    return changed


def notify_state_change() -> None:
    change_event.set()


def _touch_locked() -> None:
    state["last_update_at"] = datetime.now().strftime("%H:%M:%S")


def _snapshot_locked() -> Dict[str, Any]:
    active_call = state.get("active_call")
    return {
        "current_network": state.get("current_network"),
        "active_call": dict(active_call) if isinstance(active_call, dict) else None,
        "telegram_message_id": state.get("telegram_message_id"),
        "telegram_update_offset": state.get("telegram_update_offset", 0),
        "last_update_at": state.get("last_update_at"),
    }


def _load_from_disk(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(payload, dict):
        return {}

    return {
        key: payload.get(key)
        for key in _persistent_keys
    }


def _save_locked() -> None:
    if _state_path is None:
        return

    payload = {
        key: state.get(key)
        for key in _persistent_keys
    }
    try:
        _state_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        return
