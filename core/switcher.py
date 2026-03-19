import threading
import subprocess
from pathlib import Path
from typing import List

from core.app_logging import get_logger
from core.config import ConfigStore
from core.state import clear_active_call, update_state


MMDVMHOST_PATH = Path("/etc/mmdvmhost")
switch_lock = threading.Lock()
logger = get_logger("app.switcher")


def switch_network(network_name: str, config_store: ConfigStore) -> bool:
    with switch_lock:
        switch_completed = False
        try:
            logger.info("Switch started for network '%s'", network_name)

            source_path = config_store.get_network(network_name)
            logger.info("Loading source profile from %s", source_path)
            updated_content = source_path.read_text(encoding="utf-8")

            logger.info("Remounting filesystem as read-write")
            _run_command(["mount", "-o", "remount,rw", "/"])

            try:
                logger.info("Writing active MMDVMHost configuration")
                _write_file_atomically(MMDVMHOST_PATH, updated_content)

                logger.info("Restarting mmdvmhost service")
                _run_command(["systemctl", "restart", "mmdvmhost"])

                logger.info("Clearing MMDVM logs")
                _truncate_mmdvm_logs()
                switch_completed = True

            finally:
                logger.info("Remounting filesystem as read-only")
                try:
                    _run_command(["mount", "-o", "remount,ro", "/"])
                except subprocess.CalledProcessError:
                    logger.warning("Failed to remount filesystem as read-only after switch", exc_info=True)

        except Exception:
            logger.exception("Network switch failed for '%s'", network_name)
            return False

        if not switch_completed:
            logger.error("Switch for '%s' did not complete", network_name)
            return False

        update_state(current_network=network_name)
        clear_active_call()
        logger.info("Switch completed for network '%s'", network_name)
        return True


def _run_command(command: List[str]) -> None:
    cmd = " ".join(command)
    logger.info("Running command: %s", cmd)
    subprocess.run(["bash", "-c", cmd], check=True)


def _write_file_atomically(path: Path, content: str) -> None:
    logger.info("Updating %s using atomic copy", path)

    temp_path = "/tmp/mmdvmhost_tmp"

    with open(temp_path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info("Temporary file prepared at %s", temp_path)

    subprocess.run(["cp", str(path), "/etc/mmdvmhost.bak"], check=True)
    subprocess.run(["cp", temp_path, str(path)], check=True)
    subprocess.run(["chown", "root:root", str(path)], check=True)

    logger.info("Configuration file written successfully")


def _truncate_mmdvm_logs() -> None:
    subprocess.run(
        [
            "bash",
            "-lc",
            'shopt -s nullglob; files=(/var/log/pi-star/MMDVM-*.log); if ((${#files[@]})); then sudo truncate -s 0 "${files[@]}"; fi',
        ],
        check=True,
    )
