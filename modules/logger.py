import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict


class AppLogger:
    def __init__(self, runtime_path: Path, error_path: Path, jsonl_path: Path):
        self.runtime_path = runtime_path
        self.error_path = error_path
        self.jsonl_path = jsonl_path
        self._jsonl_lock = threading.Lock()

        self.runtime_logger = self._build_logger("runtime_logger", runtime_path, logging.INFO)
        self.error_logger = self._build_logger("error_logger", error_path, logging.ERROR)

    @staticmethod
    def _build_logger(name: str, file_path: Path, level: int) -> logging.Logger:
        logger = logging.getLogger(name)
        logger.setLevel(level)
        if not logger.handlers:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(file_path, encoding="utf-8")
            fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
            handler.setFormatter(fmt)
            logger.addHandler(handler)
        return logger

    def info(self, message: str) -> None:
        self.runtime_logger.info(message)

    def error(self, message: str) -> None:
        self.error_logger.error(message)

    def exception(self, message: str) -> None:
        self.error_logger.exception(message)

    def write_jsonl(self, payload: Dict[str, Any]) -> None:
        self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        with self._jsonl_lock:
            with self.jsonl_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
