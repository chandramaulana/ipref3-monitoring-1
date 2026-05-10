import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from modules.utils import load_json_file, save_json_file


class ScheduleManager:
    def __init__(self, schedules_path: Path):
        self.schedules_path = schedules_path
        self._lock = threading.Lock()
        self._cache: List[Dict[str, Any]] = load_json_file(schedules_path, [])

    def _save(self) -> None:
        save_json_file(self.schedules_path, self._cache)

    def list_tasks(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._cache = load_json_file(self.schedules_path, [])
            return list(self._cache)

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._cache = load_json_file(self.schedules_path, [])
            for item in self._cache:
                if item.get("id") == task_id:
                    return dict(item)
        return None

    def create_task(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            self._cache = load_json_file(self.schedules_path, [])
            now_text = datetime.now().isoformat(timespec="seconds")
            item = {
                "id": f"SCH-{str(uuid.uuid4()).split('-')[0].upper()}",
                "task_name": payload.get("task_name", "Scheduled Task"),
                "scheduled_at": payload["scheduled_at"],
                "payload": payload["payload"],
                "status": "pending",
                "last_error": "",
                "last_run_at": "",
                "created_at": now_text,
                "updated_at": now_text,
            }
            self._cache.insert(0, item)
            self._save()
            return dict(item)

    def update_task(self, task_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._cache = load_json_file(self.schedules_path, [])
            for idx, item in enumerate(self._cache):
                if item.get("id") != task_id:
                    continue
                if item.get("status") == "running":
                    return None
                item["task_name"] = payload.get("task_name", item.get("task_name", "Scheduled Task"))
                item["scheduled_at"] = payload.get("scheduled_at", item.get("scheduled_at"))
                item["payload"] = payload.get("payload", item.get("payload", {}))
                item["status"] = "pending"
                item["last_error"] = ""
                item["updated_at"] = datetime.now().isoformat(timespec="seconds")
                self._cache[idx] = item
                self._save()
                return dict(item)
        return None

    def delete_task(self, task_id: str) -> bool:
        with self._lock:
            self._cache = load_json_file(self.schedules_path, [])
            before = len(self._cache)
            self._cache = [item for item in self._cache if item.get("id") != task_id]
            changed = len(self._cache) != before
            if changed:
                self._save()
            return changed

    def due_tasks(self, now_dt: datetime) -> List[Dict[str, Any]]:
        with self._lock:
            self._cache = load_json_file(self.schedules_path, [])
            output: List[Dict[str, Any]] = []
            for item in self._cache:
                if item.get("status") != "pending":
                    continue
                try:
                    run_time = datetime.fromisoformat(item.get("scheduled_at", ""))
                except ValueError:
                    continue
                if run_time <= now_dt:
                    output.append(dict(item))
            return output

    def mark_running(self, task_id: str) -> None:
        with self._lock:
            self._cache = load_json_file(self.schedules_path, [])
            for idx, item in enumerate(self._cache):
                if item.get("id") == task_id:
                    item["status"] = "running"
                    item["last_run_at"] = datetime.now().isoformat(timespec="seconds")
                    item["updated_at"] = datetime.now().isoformat(timespec="seconds")
                    self._cache[idx] = item
                    self._save()
                    return

    def mark_failed(self, task_id: str, error: str) -> None:
        with self._lock:
            self._cache = load_json_file(self.schedules_path, [])
            for idx, item in enumerate(self._cache):
                if item.get("id") == task_id:
                    item["status"] = "failed"
                    item["last_error"] = error
                    item["updated_at"] = datetime.now().isoformat(timespec="seconds")
                    self._cache[idx] = item
                    self._save()
                    return

    def mark_completed(self, task_id: str, status: str) -> None:
        with self._lock:
            self._cache = load_json_file(self.schedules_path, [])
            for idx, item in enumerate(self._cache):
                if item.get("id") == task_id:
                    item["status"] = "completed" if status == "completed" else "stopped"
                    item["updated_at"] = datetime.now().isoformat(timespec="seconds")
                    self._cache[idx] = item
                    self._save()
                    return
