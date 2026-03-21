import glob
import os
import re
import threading
import time
from pathlib import Path
from typing import Optional

from core.app_logging import get_logger
from core.config import ConfigStore
from core.state import clear_active_call, set_active_call


DEFAULT_LOG_GLOB = "/var/log/pi-star/MMDVM-*.log"
VOICE_START_PATTERN = re.compile(
    r"(?:received\s+)?(?:rf\s+|network\s+)?voice header from\s+(?P<callsign>[A-Z0-9/_-]+).*?\bto\s+\s+(?P<tg>[A-Z0-9/_-]+)",
    re.IGNORECASE,
)
TG_PREFIX_PATTERN = re.compile(r"^[A-Za-z]+-")
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
        self._handle.seek(0, os.SEEK_END)
        self._position = self._handle.tell()
        self._inode = path.stat().st_ino

    def _close_current_file(self) -> None:
        if self._handle is not None:
            self._handle.close()
        self._handle = None
        self._current_path = None
        self._position = 0
        self._inode = None

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

        match = VOICE_START_PATTERN.search(line)
        if match:
            callsign = match.group("callsign").upper()
            talkgroup = TG_PREFIX_PATTERN.sub("", match.group("tg"))
            logger.info("Active call detected: %s -> TG %s", callsign, talkgroup)
            set_active_call(
                callsign=callsign,
                talkgroup=talkgroup,
            )
            return

        if VOICE_END_PATTERN.search(line):
            logger.info("Call ended")
            clear_active_call()
