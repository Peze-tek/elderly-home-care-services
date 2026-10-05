import json
import threading
from datetime import datetime
from pathlib import Path


class HistoryService:
    def __init__(self, history_file, max_entries):
        self.history_file = Path(history_file)
        self.max_entries = max_entries
        self.lock = threading.Lock()
        self.history_file.parent.mkdir(parents=True, exist_ok=True)

    def load(self):
        if not self.history_file.exists():
            return []
        try:
            with self.history_file.open("r", encoding="utf-8") as file:
                data = json.load(file)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            corrupt = self.history_file.with_suffix(self.history_file.suffix + ".corrupt")
            try:
                self.history_file.replace(corrupt)
            except OSError:
                pass
            return []

    def add(self, direction, transfer_type, name, size):
        try:
            with self.lock:
                history = self.load()
                history.append({
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "direction": direction,
                    "type": transfer_type,
                    "name": name,
                    "size": size,
                })
                temp = self.history_file.with_suffix(self.history_file.suffix + ".tmp")
                with temp.open("w", encoding="utf-8") as file:
                    json.dump(history[-self.max_entries:], file, indent=4, ensure_ascii=False)
                temp.replace(self.history_file)
        except OSError:
            pass
