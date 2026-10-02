import json
import os
import threading
from datetime import datetime

HISTORY_FILE = "history.json"
_lock = threading.Lock()


def add_transfer(direction, kind, name, size, peer=""):
    item = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "direction": direction,
        "type": kind,
        "name": name,
        "size": int(size),
        "peer": peer,
    }
    with _lock:
        history = load_history()
        history.append(item)
        with open(HISTORY_FILE, "w", encoding="utf-8") as file:
            json.dump(history[-1000:], file, indent=2)


def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []
