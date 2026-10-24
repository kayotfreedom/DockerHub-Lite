import json
from datetime import datetime

from config import HISTORY_FILE


def load_history() -> list:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def save_history(history: list):
    HISTORY_FILE.write_text(
        json.dumps(history[-200:], ensure_ascii=False, indent=2), encoding="utf-8"
    )


def add_history(op_type: str, message: str, status: str = "ok"):
    history = load_history()
    history.append({
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "type": op_type,
        "message": message,
        "status": status,
    })
    save_history(history)