import configparser
import os
from pathlib import Path
from typing import Dict, List, Optional


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
        self._app_config = configparser.ConfigParser()
        self._prepare_runtime_files()
        self.reload()

    def _resolve_runtime_config_dir(self, source_dir: Path) -> Path:
        override_dir = os.environ.get("PISTAR_CONTROL_DATA_DIR")
        if override_dir:
            return Path(override_dir).expanduser()

        if self._is_writable_directory(source_dir):
            return source_dir

        return Path.home() / ".config" / "pistar-control"

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
        self._app_config = configparser.ConfigParser()
        self._app_config.read(self._app_path, encoding="utf-8")
        self._ensure_defaults()

    def _ensure_defaults(self) -> None:
        changed = False

        if not self._app_config.has_section("aliases"):
            self._app_config.add_section("aliases")
            changed = True

        for host, alias in self._default_aliases.items():
            if not self._app_config.has_option("aliases", host):
                self._app_config.set("aliases", host, alias)
                changed = True

        if changed:
            with self._app_path.open("w", encoding="utf-8") as config_file:
                self._app_config.write(config_file)

    def get_app_config(self) -> Dict[str, Dict[str, str]]:
        return {
            section: {
                key: value
                for key, value in self._app_config.items(section)
            }
            for section in self._app_config.sections()
        }

    def update_app_config(self, data: Dict[str, Dict[str, str]]) -> None:
        self._app_config = configparser.ConfigParser()

        for section, values in data.items():
            self._app_config[section] = {}
            for key, value in values.items():
                self._app_config[section][key] = value

        with self._app_path.open("w", encoding="utf-8") as config_file:
            self._app_config.write(config_file)

        self.reload()

    def get_network_aliases(self) -> Dict[str, str]:
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
        return [name for name, path in self._host_paths.items() if path.exists()]

    @property
    def api_port(self) -> int:
        return self._app_config.getint("api", "port", fallback=5000)

    @property
    def api_token(self) -> str:
        return self._app_config.get("api", "token", fallback="")


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


def get_app_config() -> Dict[str, Dict[str, str]]:
    return _get_default_store().get_app_config()


def update_app_config(data: Dict[str, Dict[str, str]]) -> None:
    _get_default_store().update_app_config(data)


def get_network_aliases() -> Dict[str, str]:
    return _get_default_store().get_network_aliases()


def get_network_alias(name: str) -> str:
    return _get_default_store().get_network_alias(name)


def get_host_content(name: str) -> str:
    return _get_default_store().get_host_content(name)


def update_host_content(name: str, content: str) -> None:
    _get_default_store().update_host_content(name, content)


def _get_default_store() -> ConfigStore:
    if _default_store is None:
        raise RuntimeError("Configuration has not been loaded")

    return _default_store
