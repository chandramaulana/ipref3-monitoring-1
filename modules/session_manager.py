import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from modules.utils import load_json_file, save_json_file, utc_now_iso


class SessionManager:
    def __init__(self, history_path: Path, sessions_path: Path):
        self.history_path = history_path
        self.sessions_path = sessions_path
        self._lock = threading.Lock()
        self._sessions_cache: Dict[str, Any] = load_json_file(sessions_path, {})
        self._history_cache: List[Dict[str, Any]] = load_json_file(history_path, [])

    def generate_session_id(self) -> str:
        token = str(uuid.uuid4()).split("-")[0].upper()
        return f"TEST-{token}"

    def save_session(self, session_id: str, payload: Dict[str, Any]) -> None:
        with self._lock:
            self._sessions_cache[session_id] = payload
            save_json_file(self.sessions_path, self._sessions_cache)

    def append_history(self, payload: Dict[str, Any]) -> None:
        with self._lock:
            self._history_cache.insert(0, payload)
            save_json_file(self.history_path, self._history_cache)

    def update_history_summary(self, session_id: str, summary: Dict[str, Any]) -> None:
        with self._lock:
            for idx, item in enumerate(self._history_cache):
                if item.get("session_id") == session_id:
                    self._history_cache[idx].update(summary)
                    self._history_cache[idx]["updated_at"] = utc_now_iso()
                    save_json_file(self.history_path, self._history_cache)
                    break

    def list_history(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._history_cache = load_json_file(self.history_path, [])
            return list(self._history_cache)

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._sessions_cache = load_json_file(self.sessions_path, {})
            return self._sessions_cache.get(session_id)

    def delete_session(self, session_id: str) -> bool:
        with self._lock:
            self._sessions_cache = load_json_file(self.sessions_path, {})
            existed = session_id in self._sessions_cache
            if existed:
                del self._sessions_cache[session_id]
                save_json_file(self.sessions_path, self._sessions_cache)
            return existed

    def delete_history_item(self, session_id: str) -> bool:
        with self._lock:
            self._history_cache = load_json_file(self.history_path, [])
            before = len(self._history_cache)
            self._history_cache = [item for item in self._history_cache if item.get("session_id") != session_id]
            changed = len(self._history_cache) != before
            if changed:
                save_json_file(self.history_path, self._history_cache)
            return changed
