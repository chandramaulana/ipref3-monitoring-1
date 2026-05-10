import json
import os
import platform
import re
import shutil
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def local_now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError):
        return default


def save_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def ensure_project_paths(base_dir: Path, config: Dict[str, Any]) -> None:
    for _, rel_path in config.get("log_paths", {}).items():
        (base_dir / rel_path).parent.mkdir(parents=True, exist_ok=True)
    for _, rel_path in config.get("data_paths", {}).items():
        (base_dir / rel_path).parent.mkdir(parents=True, exist_ok=True)


def read_config(config_path: Path) -> Dict[str, Any]:
    with config_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def is_windows() -> bool:
    return platform.system().lower().startswith("win")


def detect_iperf_binary() -> Tuple[bool, str]:
    candidate = shutil.which("iperf3")
    if candidate:
        return True, candidate
    return False, "iperf3 not found in PATH"


def build_ping_command(host: str):
    if is_windows():
        return ["ping", "-n", "1", host]
    return ["ping", "-c", "1", host]


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def sanitize_text(value: str, fallback: str = "") -> str:
    text = (value or "").strip()
    return text if text else fallback


def validate_host(host: str) -> bool:
    host = sanitize_text(host)
    if not host:
        return False

    if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", host):
        return all(0 <= int(part) <= 255 for part in host.split("."))

    try:
        socket.getaddrinfo(host, None)
        return True
    except socket.gaierror:
        return False


def clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(value, maximum))


def readable_protocol(protocol: str) -> str:
    p = (protocol or "").upper()
    return p if p in {"TCP", "UDP"} else "TCP"


def rolling_average(values, precision: int = 3) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), precision)
