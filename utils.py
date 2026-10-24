import os
import shutil
import subprocess
from pathlib import Path

from config import SCRIPT_TIMEOUT


def decode_bytes(data: bytes) -> str:
    if not data:
        return ""
    for enc in ("utf-8", "cp866", "cp1251"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def make_env(repo_path: Path, script_path: Path) -> dict:
    env = os.environ.copy()
    env["REPO_DIR"] = str(repo_path)
    env["SCRIPT_PATH"] = str(script_path)
    env["PWD"] = str(repo_path)
    env["LANG"] = "en_US.UTF-8"
    env["LC_ALL"] = "en_US.UTF-8"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def find_bash():
    bash = shutil.which("bash")
    if bash:
        return bash
    candidates = [
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
        r"C:\Windows\System32\bash.exe",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None


def is_text_file(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            chunk = f.read(1024)
        if b"\x00" in chunk:
            return False
        chunk.decode("utf-8")
        return True
    except Exception:
        return False


def run_bash_script(bash_exe: str, script_path: Path, repo_path: Path) -> dict:
    try:
        result = subprocess.run(
            [bash_exe, str(script_path)],
            cwd=str(script_path.parent),
            capture_output=True,
            timeout=SCRIPT_TIMEOUT,
            env=make_env(repo_path, script_path),
        )
        return {
            "returncode": result.returncode,
            "stdout": decode_bytes(result.stdout),
            "stderr": decode_bytes(result.stderr),
        }
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout": "", "stderr": f"Таймаут ({SCRIPT_TIMEOUT} сек)."}
    except Exception as e:
        return {"returncode": -2, "stdout": "", "stderr": f"Ошибка: {e}"}