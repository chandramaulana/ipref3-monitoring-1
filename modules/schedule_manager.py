import threading
import uuid
from datetime import datetime, timedelta
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

    def _normalize_task(self, item: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(item)
        start_at = normalized.get("start_at", "")
        end_at = normalized.get("end_at", "")
        scheduled_at = normalized.get("scheduled_at", "")

        if (not start_at or not end_at) and scheduled_at:
            start_at = start_at or scheduled_at
            if not end_at:
                auto_stop = 5
                try:
                    auto_stop = max(1, int((normalized.get("payload") or {}).get("auto_stop_minutes", 5)))
                except (TypeError, ValueError):
                    auto_stop = 5
                try:
                    end_at = (datetime.fromisoformat(start_at) + timedelta(minutes=auto_stop)).isoformat(timespec="minutes")
                except ValueError:
                    end_at = start_at

        normalized["start_at"] = start_at or ""
        normalized["end_at"] = end_at or ""
        if not normalized.get("scheduled_at"):
            normalized["scheduled_at"] = normalized["start_at"]
        return normalized

    def _task_window(self, item: Dict[str, Any]) -> Optional[tuple[datetime, datetime]]:
        normalized = self._normalize_task(item)
        try:
            start_dt = datetime.fromisoformat(normalized.get("start_at", ""))
            end_dt = datetime.fromisoformat(normalized.get("end_at", ""))
        except ValueError:
            return None
        if end_dt <= start_dt:
            return None
        return start_dt, end_dt

    def list_tasks(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._cache = load_json_file(self.schedules_path, [])
            return [self._normalize_task(item) for item in self._cache]

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._cache = load_json_file(self.schedules_path, [])
            for item in self._cache:
                if item.get("id") == task_id:
                    return self._normalize_task(item)
        return None

    def find_overlapping_task(self, start_at: str, end_at: str, exclude_task_id: str = "") -> Optional[Dict[str, Any]]:
        with self._lock:
            self._cache = load_json_file(self.schedules_path, [])
            try:
                new_start = datetime.fromisoformat(start_at)
                new_end = datetime.fromisoformat(end_at)
            except ValueError:
                return None

            if new_end <= new_start:
                return None

            for item in self._cache:
                if exclude_task_id and item.get("id") == exclude_task_id:
                    continue
                window = self._task_window(item)
                if not window:
                    continue
                existing_start, existing_end = window
                if new_start < existing_end and existing_start < new_end:
                    return self._normalize_task(item)
        return None

    def create_task(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            self._cache = load_json_file(self.schedules_path, [])
            now_text = datetime.now().isoformat(timespec="seconds")
            item = {
                "id": f"SCH-{str(uuid.uuid4()).split('-')[0].upper()}",
                "task_name": payload.get("task_name", "Scheduled Task"),
                "start_at": payload["start_at"],
                "end_at": payload["end_at"],
                "scheduled_at": payload["start_at"],
                "payload": payload["payload"],
                "status": "pending",
                "last_error": "",
                "last_run_at": "",
                "created_at": now_text,
                "updated_at": now_text,
            }
            self._cache.insert(0, item)
            self._save()
            return self._normalize_task(item)

    def update_task(self, task_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._cache = load_json_file(self.schedules_path, [])
            for idx, item in enumerate(self._cache):
                if item.get("id") != task_id:
                    continue
                if item.get("status") == "running":
                    return None
                item["task_name"] = payload.get("task_name", item.get("task_name", "Scheduled Task"))
                item["start_at"] = payload.get("start_at", item.get("start_at", item.get("scheduled_at", "")))
                item["end_at"] = payload.get("end_at", item.get("end_at", item.get("scheduled_at", "")))
                item["scheduled_at"] = item.get("start_at", "")
                item["payload"] = payload.get("payload", item.get("payload", {}))
                item["status"] = "pending"
                item["last_error"] = ""
                item["updated_at"] = datetime.now().isoformat(timespec="seconds")
                self._cache[idx] = item
                self._save()
                return self._normalize_task(item)
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
                window = self._task_window(item)
                if not window:
                    continue
                start_dt, end_dt = window
                if start_dt <= now_dt <= end_dt:
                    output.append(self._normalize_task(item))
            return output

    def expired_pending_tasks(self, now_dt: datetime) -> List[Dict[str, Any]]:
        with self._lock:
            self._cache = load_json_file(self.schedules_path, [])
            output: List[Dict[str, Any]] = []
            for item in self._cache:
                if item.get("status") != "pending":
                    continue
                window = self._task_window(item)
                if not window:
                    continue
                _, end_dt = window
                if now_dt > end_dt:
                    output.append(self._normalize_task(item))
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
