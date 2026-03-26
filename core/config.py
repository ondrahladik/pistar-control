import configparser
import os
import re
import tempfile
import threading
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional

from core.timezone_utils import get_effective_timezone_name as resolve_effective_timezone_name


class ConfigStore:
    def __init__(self, config_dir: str, app_config_path: str) -> None:
        self._source_config_dir = Path(config_dir)
        self._source_app_path = Path(app_config_path)
        self._config_dir = self._resolve_runtime_config_dir(self._source_config_dir)
        self._app_path = self._config_dir / self._source_app_path.name
        self._host_paths = {
            "host1": self._config_dir / "host1",
            "host2": self._config_dir / "host2",
        }
        self._default_aliases = {
            "host1": "Síť 1",
            "host2": "Síť 2",
        }
        self._default_api_config = {
            "port": "5000",
            "token": "pistar",
        }
        self._default_general_config = {
            "timezone": "system",
        }
        self._default_telegram_config = {
            "enabled": "false",
            "bot_token": "",
            "chat_id": "",
            "thread_id": "",
        }
        self._default_mqtt_config = {
            "enabled": "false",
            "server": "",
            "port": "1883",
            "username": "",
            "password": "",
            "topic_pub": "",
            "topic_sub": "",
        }
        self._lock = threading.RLock()
        self._app_config = configparser.ConfigParser()
        self._prepare_runtime_files()
        self.reload()

    def _resolve_runtime_config_dir(self, source_dir: Path) -> Path:
        override_dir = os.environ.get("PISTAR_CONTROL_DATA_DIR")
        if override_dir:
            return Path(override_dir).expanduser()

        for candidate in self._runtime_dir_candidates(source_dir):
            if self._is_writable_directory(candidate):
                return candidate

        # As a last resort, use a temp directory so the app can still start.
        return Path(tempfile.gettempdir()) / "pistar-control"

    def _runtime_dir_candidates(self, source_dir: Path) -> List[Path]:
        candidates: List[Path] = [source_dir]

        sudo_user = os.environ.get("SUDO_USER")
        if sudo_user:
            sudo_home = Path("/home") / sudo_user / ".config" / "pistar-control"
            candidates.append(sudo_home)

        candidates.extend(
            [
                Path.home() / ".config" / "pistar-control",
                Path("/var/log/pi-star") / "pistar-control",
                Path("/tmp") / "pistar-control",
            ]
        )

        unique_candidates: List[Path] = []
        seen = set()
        for candidate in candidates:
            normalized = str(candidate)
            if normalized in seen:
                continue
            seen.add(normalized)
            unique_candidates.append(candidate)

        return unique_candidates

    def _prepare_runtime_files(self) -> None:
        self._config_dir.mkdir(parents=True, exist_ok=True)
        self._copy_if_missing(self._source_app_path, self._app_path)

        for host_name, host_path in self._host_paths.items():
            self._copy_if_missing(self._source_config_dir / host_name, host_path)

    @staticmethod
    def _copy_if_missing(source: Path, destination: Path) -> None:
        if destination.exists() or not source.exists():
            return

        destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    @staticmethod
    def _is_writable_directory(path: Path) -> bool:
        try:
            path.mkdir(parents=True, exist_ok=True)
            test_file = path / ".write_test"
            with test_file.open("w", encoding="utf-8") as handle:
                handle.write("ok")
            test_file.unlink()
            return True
        except OSError:
            return False

    def reload(self) -> None:
        with self._lock:
            self._app_config = configparser.ConfigParser()
            self._app_config.read(self._app_path, encoding="utf-8")
            self._ensure_defaults()

    def _ensure_defaults(self) -> None:
        changed = False

        if not self._app_config.has_section("api"):
            self._app_config.add_section("api")
            changed = True

        for key, value in self._default_api_config.items():
            if not self._app_config.has_option("api", key):
                self._app_config.set("api", key, value)
                changed = True

        if not self._app_config.has_section("general"):
            self._app_config.add_section("general")
            changed = True

        for key, value in self._default_general_config.items():
            if not self._app_config.has_option("general", key):
                self._app_config.set("general", key, value)
                changed = True

        if not self._app_config.has_section("aliases"):
            self._app_config.add_section("aliases")
            changed = True

        for host, alias in self._default_aliases.items():
            if not self._app_config.has_option("aliases", host):
                self._app_config.set("aliases", host, alias)
                changed = True

        if not self._app_config.has_section("telegram"):
            self._app_config.add_section("telegram")
            changed = True

        for key, value in self._default_telegram_config.items():
            if not self._app_config.has_option("telegram", key):
                self._app_config.set("telegram", key, value)
                changed = True

        if not self._app_config.has_section("mqtt"):
            self._app_config.add_section("mqtt")
            changed = True

        legacy_topic = self._app_config.get("mqtt", "topic", fallback="")
        if legacy_topic and not self._app_config.has_option("mqtt", "topic_pub"):
            self._app_config.set("mqtt", "topic_pub", legacy_topic)
            changed = True

        for key, value in self._default_mqtt_config.items():
            if not self._app_config.has_option("mqtt", key):
                self._app_config.set("mqtt", key, value)
                changed = True

        if changed:
            with self._app_path.open("w", encoding="utf-8") as config_file:
                self._app_config.write(config_file)

    def get_app_config(self) -> Dict[str, Dict[str, str]]:
        with self._lock:
            return {
                section: {
                    key: value
                    for key, value in self._app_config.items(section)
                }
                for section in self._app_config.sections()
            }
        

    def update_app_config(self, data: Dict[str, Dict[str, str]]) -> None:
        with self._lock:
            current_config = self.get_app_config()
            preserved_fields = {
                ("api", "token"),
                ("telegram", "bot_token"),
                ("telegram", "chat_id"),
                ("mqtt", "password"),
            }

            self._app_config = configparser.ConfigParser()

            for section, values in data.items():
                self._app_config[section] = {}
                for key, value in values.items():
                    next_value = value
                    if (
                        (section, key) in preserved_fields
                        and value == ""
                        and section in current_config
                        and key in current_config[section]
                    ):
                        next_value = current_config[section][key]
                    self._app_config[section][key] = next_value

            with self._app_path.open("w", encoding="utf-8") as config_file:
                self._app_config.write(config_file)

            self.reload()

    def get_network_aliases(self) -> Dict[str, str]:
        with self._lock:
            aliases = {
                host: self._app_config.get("aliases", host, fallback=default_alias)
                for host, default_alias in self._default_aliases.items()
            }
            return {
                host: aliases.get(host, host)
                for host in self.list_networks()
            }

    def get_network_alias(self, name: str) -> str:
        return self.get_network_aliases().get(name, name)

    def get_network(self, name: str) -> Path:
        if name not in self._host_paths:
            raise KeyError(f"Unknown network: {name}")

        return self._host_paths[name]

    def get_host_content(self, name: str) -> str:
        return self.get_network(name).read_text(encoding="utf-8")

    def update_host_content(self, name: str, content: str) -> None:
        self.get_network(name).write_text(content, encoding="utf-8")

    def list_networks(self) -> List[str]:
        with self._lock:
            return [name for name, path in self._host_paths.items() if path.exists()]

    def get_basic_host_settings(self, name: str) -> Dict[str, str]:
        if name not in self._host_paths:
            return {}

        parser = configparser.ConfigParser()
        try:
            parser.read_string(self.get_host_content(name))
        except (OSError, configparser.Error):
            return {}

        return {
            "callsign": parser.get("General", "Callsign", fallback=""),
            "id": parser.get("General", "Id", fallback=""),
        }

    def detect_network_by_content(self, active_config_path: Path) -> Optional[str]:
        try:
            active_content = active_config_path.read_text(encoding="utf-8")
        except OSError:
            return None

        normalized_active_content = _normalize_config_content(active_content)
        if not normalized_active_content:
            return None

        with self._lock:
            for name, path in self._host_paths.items():
                if not path.exists():
                    continue
                try:
                    candidate_content = path.read_text(encoding="utf-8")
                except OSError:
                    continue

                if _normalize_config_content(candidate_content) == normalized_active_content:
                    return name

        return None

    @property
    def api_port(self) -> int:
        with self._lock:
            return self._app_config.getint("api", "port", fallback=5000)

    @property
    def api_token(self) -> str:
        with self._lock:
            return self._app_config.get("api", "token", fallback="")

    @property
    def runtime_state_path(self) -> Path:
        return self._config_dir / "runtime-state.json"

    def get_telegram_config(self) -> Dict[str, str]:
        with self._lock:
            return {
                key: self._app_config.get("telegram", key, fallback=value)
                for key, value in self._default_telegram_config.items()
            }

    def get_general_config(self) -> Dict[str, str]:
        with self._lock:
            return {
                key: self._app_config.get("general", key, fallback=value)
                for key, value in self._default_general_config.items()
            }

    def get_timezone_name(self) -> str:
        with self._lock:
            return self._app_config.get("general", "timezone", fallback="system")

    def get_effective_timezone_name(self) -> str:
        return resolve_effective_timezone_name(self.get_timezone_name())

    def get_telegram_aliases(self) -> Dict[str, str]:
        aliases: Dict[str, str] = {}
        for network, alias in self.get_network_aliases().items():
            normalized_command = _normalize_command_alias(alias)
            if normalized_command:
                aliases[normalized_command] = network
        return aliases

    def get_mqtt_config(self) -> Dict[str, str]:
        with self._lock:
            return {
                key: self._app_config.get("mqtt", key, fallback=value)
                for key, value in self._default_mqtt_config.items()
            }


_default_store: Optional[ConfigStore] = None


def load_config(
    config_dir: str = "config",
    app_config_path: str = "config/app.ini",
) -> ConfigStore:
    global _default_store
    _default_store = ConfigStore(
        config_dir=config_dir,
        app_config_path=app_config_path,
    )
    return _default_store


def get_network(name: str) -> Path:
    return _get_default_store().get_network(name)


def list_networks() -> List[str]:
    return _get_default_store().list_networks()


def get_api_port() -> int:
    return _get_default_store().api_port


def get_api_token() -> str:
    return _get_default_store().api_token


def get_runtime_state_path() -> Path:
    return _get_default_store().runtime_state_path


def get_app_config() -> Dict[str, Dict[str, str]]:
    return _get_default_store().get_app_config()


def update_app_config(data: Dict[str, Dict[str, str]]) -> None:
    _get_default_store().update_app_config(data)


def get_network_aliases() -> Dict[str, str]:
    return _get_default_store().get_network_aliases()


def get_network_alias(name: str) -> str:
    return _get_default_store().get_network_alias(name)


def get_telegram_config() -> Dict[str, str]:
    return _get_default_store().get_telegram_config()


def get_general_config() -> Dict[str, str]:
    return _get_default_store().get_general_config()


def get_timezone_name() -> str:
    return _get_default_store().get_timezone_name()


def get_effective_timezone_name() -> str:
    return _get_default_store().get_effective_timezone_name()


def get_telegram_aliases() -> Dict[str, str]:
    return _get_default_store().get_telegram_aliases()


def get_mqtt_config() -> Dict[str, str]:
    return _get_default_store().get_mqtt_config()


def get_host_content(name: str) -> str:
    return _get_default_store().get_host_content(name)


def update_host_content(name: str, content: str) -> None:
    _get_default_store().update_host_content(name, content)


def get_basic_host_settings(name: str) -> Dict[str, str]:
    return _get_default_store().get_basic_host_settings(name)


def _get_default_store() -> ConfigStore:
    if _default_store is None:
        raise RuntimeError("Configuration has not been loaded")

    return _default_store


def _normalize_command_alias(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    uppercase_shortcut = "".join(character for character in ascii_value if character.isupper())
    if 2 <= len(uppercase_shortcut) <= 4:
        return uppercase_shortcut.lower()

    normalized = re.sub(r"[^a-zA-Z0-9]+", "", ascii_value).lower()
    return normalized


def _normalize_config_content(value: str) -> str:
    return value.replace("\r\n", "\n").strip()
