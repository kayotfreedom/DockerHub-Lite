import sys
from pathlib import Path

# Базовая папка для ресурсов PyInstaller (templates, static)
if getattr(sys, 'frozen', False):
    # .exe: ресурсы распакованы во временную папку _MEIPASS
    RESOURCES_DIR = Path(sys._MEIPASS)
    # Данные (repos, history.json) — в фиксированной папке, не удаляются
    DATA_DIR = Path(r"C:\DockerHubLiteTemp\Files")
else:
    # Обычный запуск из исходников
    BASE_DIR = Path(__file__).parent
    RESOURCES_DIR = BASE_DIR
    DATA_DIR = BASE_DIR / "data"

# Создаём папку данных, если её нет
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Репозитории и история — в DATA_DIR
REPOS_DIR = DATA_DIR / "repos"
REPOS_DIR.mkdir(exist_ok=True)

HISTORY_FILE = DATA_DIR / "history.json"

# ---------- Константы (без изменений) ----------
import re

DEPENDENCY_ERROR_PATTERNS = [
    re.compile(r"ModuleNotFoundError", re.I),
    re.compile(r"No module named", re.I),
    re.compile(r"ImportError", re.I),
    re.compile(r"ModuleNotFound", re.I),
]

PYTHON3_NOT_FOUND_PATTERNS = [
    re.compile(r"Python was not found", re.I),
    re.compile(r"python3:\s*command not found", re.I),
    re.compile(r"python3:\s*not found", re.I),
    re.compile(r"bash:\s*python3:\s*command not found", re.I),
    re.compile(r"'python3'\s*is not recognized", re.I),
    re.compile(r"python3.*No such file", re.I),
    re.compile(r"^\s*Python\s*$", re.I),
    re.compile(r"^\s*Python\s+", re.I),
    re.compile(r"Microsoft Store", re.I),
    re.compile(r"App Execution Aliases", re.I),
]

WHEEL_BUILD_ERROR_PATTERNS = [
    re.compile(r"Failed building wheel for ([\w\-\.]+)", re.I),
    re.compile(r"ERROR: Failed building wheel for ([\w\-\.]+)", re.I),
    re.compile(r"error:.*building wheel for ([\w\-\.]+)", re.I),
    re.compile(r"Building wheel for ([\w\-\.]+) .*error", re.I),
    re.compile(r"Failed to build ([\w\-\.]+)", re.I),
    re.compile(r"ERROR: Failed to build ([\w\-\.]+)", re.I),
    re.compile(r"Could not build wheels? for ([\w\-\.]+)", re.I),
]

_NOT_PACKAGES = {
    "installable", "wheels", "wheel", "packages", "package",
    "project", "projects", "some", "the", "a", "an",
    "install", "installation", "requirements", "requirement",
}

SCRIPT_TIMEOUT = 300
MAX_LOG_LINES = 2000
LONG_RUNNING_THRESHOLD = 10

LONG_RUNNING_MARKERS = [
    re.compile(r"Listening on", re.I),
    re.compile(r"Uvicorn running", re.I),
    re.compile(r"Bot started", re.I),
    re.compile(r"Started", re.I),
    re.compile(r"Server started", re.I),
    re.compile(r"Now running", re.I),
    re.compile(r"Running on", re.I),
    re.compile(r"Connected", re.I),
]

KNOWN_EXECUTORS = {
    "bash", "sh", "zsh",
    "python", "python3", "python2",
    "node", "nodejs", "npm", "npx", "yarn", "pnpm",
    "ruby", "perl", "php",
    "pwsh", "powershell", "cmd",
    "java", "go", "dotnet",
    "deno", "bun",
}

SAFE_RUN_COMMANDS = {
    "mkdir", "echo", "cd", "pwd", "ls", "dir",
    "touch", "cp", "copy", "mv", "move",
    "cat", "type", "head", "tail",
    "true", "false", "test",
}

UNSAFE_RUN_COMMANDS = {
    "apt", "apt-get", "yum", "dnf", "pacman", "apk", "brew",
    "pip", "pip3", "npm", "yarn", "pnpm",
    "curl", "wget", "git", "ssh", "scp",
    "sudo", "su", "systemctl", "service",
    "docker", "docker-compose", "kubectl",
}

ARCHIVE_EXTENSIONS = {".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz", ".zip"}

build_queues: dict = {}
running_processes: dict = {}