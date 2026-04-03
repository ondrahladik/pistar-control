import glob
import os
import re
import threading
import time
from collections import deque
from pathlib import Path
from typing import Deque, Dict, List, Optional

from core.app_logging import get_logger
from core.config import ConfigStore
from core.state import clear_active_call, set_active_call
from core.timezone_utils import convert_local_time


DEFAULT_LOG_GLOB = "/var/log/pi-star/MMDVM-*.log"
RECENT_CALLS_LIMIT = 10
VOICE_START_PATTERN = re.compile(
    r"(?:received\s+)?(?:rf\s+|network\s+)?voice header from\s+(?P<callsign>[A-Z0-9/_-]+).*?\bto\s+TG\s+(?P<tg>[A-Z0-9/_-]+)",
    re.IGNORECASE,
)
VOICE_END_DETAILS_PATTERN = re.compile(
    r"end of voice transmission"
    r"(?:\s+from\s+(?P<callsign>[A-Z0-9/_-]+)\s+to\s+TG\s+(?P<tg>[A-Z0-9/_-]+))?"
    r"(?:,\s*(?P<duration>\d+(?:\.\d+)?)\s+seconds?"
    r",\s*(?P<loss>\d+(?:\.\d+)?)%\s+packet loss"
    r",\s*BER:\s*(?P<ber>\d+(?:\.\d+)?)%?)?",
    re.IGNORECASE,
)
TG_PREFIX_PATTERN = re.compile(r"^[A-Za-z]+-")
LOG_TIME_PATTERN = re.compile(r"\b(?P<time>\d{2}:\d{2}:\d{2})\b")
VOICE_END_PATTERN = re.compile(r"end of voice transmission", re.IGNORECASE)
logger = get_logger("app.log-parser")


class LogParserService:
    def __init__(self, config_store: ConfigStore, poll_interval: float = 0.5) -> None:
        self._config_store = config_store
        self._poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._current_path: Optional[Path] = None
        self._handle = None
        self._position = 0
        self._inode: Optional[int] = None
        self._recent_calls: Deque[Dict[str, Optional[str]]] = deque(maxlen=RECENT_CALLS_LIMIT)
        self._recent_calls_lock = threading.Lock()
        self._active_recent_call: Optional[Dict[str, Optional[str]]] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run,
            name="mmdvm-log-parser",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._close_current_file()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._follow_once()
            except Exception:
                logger.exception("Log parser iteration failed")
                time.sleep(1.0)

    def _follow_once(self) -> None:
        self._config_store.reload()
        latest_path = self._find_latest_log()
        if latest_path is None:
            self._close_current_file()
            time.sleep(self._poll_interval)
            return

        if self._should_reopen(latest_path):
            self._open_log(latest_path)

        if self._handle is None:
            time.sleep(self._poll_interval)
            return

        line = self._handle.readline()
        if line:
            self._position = self._handle.tell()
            self._process_line(line.strip())
            return

        if self._file_rotated():
            self._open_log(latest_path)
            return

        time.sleep(self._poll_interval)

    def _find_latest_log(self) -> Optional[Path]:
        candidates = [Path(path) for path in glob.glob(DEFAULT_LOG_GLOB)]
        if not candidates:
            return None
        return max(candidates, key=lambda candidate: candidate.stat().st_mtime)

    def _should_reopen(self, latest_path: Path) -> bool:
        return self._handle is None or self._current_path != latest_path

    def _open_log(self, path: Path) -> None:
        self._close_current_file()
        self._current_path = path
        self._handle = path.open("r", encoding="utf-8", errors="ignore")
        self._replace_recent_calls(self._read_recent_calls_from_log(path))
        self._handle.seek(0, os.SEEK_END)
        self._position = self._handle.tell()
        self._inode = path.stat().st_ino

    def get_recent_calls(self) -> List[Dict[str, Optional[str]]]:
        with self._recent_calls_lock:
            return [self._serialize_recent_call(call) for call in reversed(self._recent_calls)]

    def _close_current_file(self) -> None:
        if self._handle is not None:
            self._handle.close()
        self._handle = None
        self._current_path = None
        self._position = 0
        self._inode = None
        self._active_recent_call = None

    def _file_rotated(self) -> bool:
        if self._current_path is None:
            return False

        try:
            stat_result = self._current_path.stat()
        except OSError:
            return True

        if self._inode is not None and stat_result.st_ino != self._inode:
            return True
        return stat_result.st_size < self._position

    def _process_line(self, line: str) -> None:
        if not line:
            return

        started_call = self._parse_recent_call(line)
        if started_call is not None:
            logger.info(
                "Active call detected: %s -> TG %s",
                started_call["callsign"],
                started_call["talkgroup"],
            )
            self._active_recent_call = started_call
            set_active_call(
                callsign=started_call["callsign"] or "?",
                talkgroup=started_call["talkgroup"] or "?",
            )
            return

        if VOICE_END_PATTERN.search(line):
            logger.info("Call ended")
            self._finish_active_call(self._parse_completed_recent_call(line))
            clear_active_call()

    def _read_recent_calls_from_log(self, path: Path) -> Deque[Dict[str, Optional[str]]]:
        recent_calls: Deque[Dict[str, Optional[str]]] = deque(maxlen=RECENT_CALLS_LIMIT)
        active_recent_call: Optional[Dict[str, Optional[str]]] = None

        try:
            with path.open("r", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    normalized_line = line.strip()
                    started_call = self._parse_recent_call(normalized_line)
                    if started_call is not None:
                        active_recent_call = started_call
                        continue

                    completed_call = self._parse_completed_recent_call(normalized_line)
                    if VOICE_END_PATTERN.search(normalized_line):
                        merged_call = self._merge_recent_call_details(active_recent_call, completed_call)
                        if merged_call is not None:
                            self._append_unique_recent_call(recent_calls, merged_call)
                        active_recent_call = None
        except OSError:
            logger.warning("Unable to preload recent calls from %s", path)

        return recent_calls

    def _parse_recent_call(self, line: str) -> Optional[Dict[str, Optional[str]]]:
        match = VOICE_START_PATTERN.search(line)
        if not match:
            return None

        return {
            "callsign": match.group("callsign").upper(),
            "talkgroup": TG_PREFIX_PATTERN.sub("", match.group("tg")),
            "time_raw": self._extract_log_time(line),
            "duration": None,
            "loss": None,
            "ber": None,
        }

    def _parse_completed_recent_call(self, line: str) -> Optional[Dict[str, Optional[str]]]:
        match = VOICE_END_DETAILS_PATTERN.search(line)
        if not match:
            return None

        callsign = match.group("callsign")
        talkgroup = match.group("tg")
        return {
            "callsign": callsign.upper() if callsign else None,
            "talkgroup": TG_PREFIX_PATTERN.sub("", talkgroup) if talkgroup else None,
            "time_raw": self._extract_log_time(line),
            "duration": match.group("duration"),
            "loss": match.group("loss"),
            "ber": match.group("ber"),
        }

    def _extract_log_time(self, line: str) -> Optional[str]:
        match = LOG_TIME_PATTERN.search(line)
        if match:
            return match.group("time")
        return None

    def _finish_active_call(self, completed_call: Optional[Dict[str, Optional[str]]] = None) -> None:
        merged_call = self._merge_recent_call_details(self._active_recent_call, completed_call)
        if merged_call is None:
            return

        self._append_recent_call(merged_call)
        self._active_recent_call = None

    def _append_recent_call(self, recent_call: Dict[str, Optional[str]]) -> None:
        with self._recent_calls_lock:
            self._append_unique_recent_call(self._recent_calls, recent_call)

    def _replace_recent_calls(self, recent_calls: Deque[Dict[str, Optional[str]]]) -> None:
        with self._recent_calls_lock:
            self._recent_calls = deque(recent_calls, maxlen=RECENT_CALLS_LIMIT)

    def _merge_recent_call_details(
        self,
        active_call: Optional[Dict[str, Optional[str]]],
        completed_call: Optional[Dict[str, Optional[str]]],
    ) -> Optional[Dict[str, Optional[str]]]:
        if active_call is None and completed_call is None:
            return None
        if active_call is None:
            return dict(completed_call) if completed_call is not None else None
        if completed_call is None:
            return dict(active_call)

        merged_call = dict(active_call)
        for key, value in completed_call.items():
            if value is not None and not merged_call.get(key):
                merged_call[key] = value
                continue
            if key in {"duration", "loss", "ber", "time_raw"} and value is not None:
                merged_call[key] = value
        return merged_call

    def _append_unique_recent_call(
        self,
        recent_calls: Deque[Dict[str, Optional[str]]],
        recent_call: Dict[str, Optional[str]],
    ) -> None:
        callsign = recent_call.get("callsign")
        if not callsign:
            return

        deduplicated_calls = [
            existing_call
            for existing_call in recent_calls
            if existing_call.get("callsign") != callsign
        ]
        deduplicated_calls.append(dict(recent_call))
        recent_calls.clear()
        recent_calls.extend(deduplicated_calls[-RECENT_CALLS_LIMIT:])

    def _serialize_recent_call(self, recent_call: Dict[str, Optional[str]]) -> Dict[str, Optional[str]]:
        serialized_call = {
            key: value
            for key, value in recent_call.items()
            if key != "time_raw"
        }
        serialized_call["time"] = convert_local_time(
            recent_call.get("time_raw"),
            self._config_store.get_timezone_name(),
            source_timezone_name="UTC",
        )
        return serialized_call
