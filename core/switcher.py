import os
import subprocess
import tempfile
import traceback
from pathlib import Path
from typing import List

from core.config import ConfigStore
from core.state import lock, state


MMDVMHOST_PATH = Path("/etc/mmdvmhost")


def switch_network(network_name: str, config_store: ConfigStore) -> bool:
    with lock:
        try:
            print("=== SWITCH NETWORK START ===")
            print("Target network:", network_name)

            source_path = config_store.get_network(network_name)
            print("Copying source file:", source_path)
            updated_content = source_path.read_text(encoding="utf-8")

            print("Switching filesystem to RW")
            _run_command(["mount", "-o", "remount,rw", "/"])

            try:
                print("Writing updated config...")
                _write_file_atomically(MMDVMHOST_PATH, updated_content)

                print("Restarting mmdvmhost...")
                _run_command(["systemctl", "restart", "mmdvmhost"])

            finally:
                print("Switching filesystem back to RO")
                _run_command(["mount", "-o", "remount,ro", "/"])

        except Exception as e:
            print("!!! ERROR in switch_network !!!")
            traceback.print_exc()
            return False

        state["current_network"] = network_name
        print("=== SWITCH SUCCESS ===")
        return True


def _run_command(command: List[str]) -> None:
    cmd = " ".join(command)
    print("Running command:", cmd)
    subprocess.run(["bash", "-c", cmd], check=True)


def _write_file_atomically(path: Path, content: str) -> None:
    print("Writing file using cp...")

    temp_path = "/tmp/mmdvmhost_tmp"

    with open(temp_path, "w", encoding="utf-8") as f:
        f.write(content)

    print("Temp file written:", temp_path)

    subprocess.run(["cp", str(path), "/etc/mmdvmhost.bak"], check=True)
    subprocess.run(["cp", temp_path, str(path)], check=True)
    subprocess.run(["chown", "root:root", str(path)], check=True)

    print("File copied successfully")