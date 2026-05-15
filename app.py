import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from flask import Flask, Response, jsonify, render_template, request
from flask_socketio import SocketIO

from modules.exporter import apply_filters, export_csv, export_excel, export_filename, export_json, export_jsonl
from modules.iperf_runner import IperfTestRunner
from modules.logger import AppLogger
from modules.schedule_manager import ScheduleManager
from modules.session_manager import SessionManager
from modules.statistics import LiveStatistics
from modules.utils import (
    clamp,
    detect_iperf_binary,
    ensure_project_paths,
    load_json_file,
    local_now_text,
    read_config,
    readable_protocol,
    save_json_file,
    sanitize_text,
    validate_host,
)

BASE_DIR = Path(__file__).resolve().parent
CONFIG = read_config(BASE_DIR / "config.json")
ensure_project_paths(BASE_DIR, CONFIG)

app = Flask(__name__)
app.config["SECRET_KEY"] = CONFIG.get("secret_key", "secret")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode=CONFIG.get("socketio_async_mode", "threading"))

logger = AppLogger(
    runtime_path=BASE_DIR / CONFIG["log_paths"]["runtime"],
    error_path=BASE_DIR / CONFIG["log_paths"]["error"],
    jsonl_path=BASE_DIR / CONFIG["log_paths"]["jsonl"],
)
session_manager = SessionManager(
    history_path=BASE_DIR / CONFIG["data_paths"]["history"],
    sessions_path=BASE_DIR / CONFIG["data_paths"]["sessions"],
)
schedules_path = BASE_DIR / CONFIG.get("data_paths", {}).get("schedules", "data/schedules.json")
schedule_manager = ScheduleManager(schedules_path=schedules_path)
deleted_sessions_path = BASE_DIR / "data" / "deleted_sessions.json"

state_lock = threading.Lock()
active_runner: IperfTestRunner | None = None
active_session: Dict[str, Any] | None = None
last_task_payload: Dict[str, Any] | None = None
live_stats = LiveStatistics()
scheduler_stop_event = threading.Event()
scheduler_thread: threading.Thread | None = None


def _load_deleted_session_ids() -> set[str]:
    payload = load_json_file(deleted_sessions_path, [])
    if isinstance(payload, dict):
        payload = payload.get("session_ids", [])
    if not isinstance(payload, list):
        return set()
    return {str(item).strip() for item in payload if str(item).strip()}


def _save_deleted_session_ids(session_ids: set[str]) -> None:
    save_json_file(deleted_sessions_path, sorted(session_ids))


def _is_session_deleted(session_id: str) -> bool:
    return session_id in _load_deleted_session_ids()


def _mark_session_deleted(session_id: str) -> None:
    if not session_id:
        return
    deleted = _load_deleted_session_ids()
    if session_id in deleted:
        return
    deleted.add(session_id)
    _save_deleted_session_ids(deleted)


def _session_exists_in_jsonl(session_id: str) -> bool:
    if not session_id:
        return False
    for item in _load_jsonl_records():
        if item.get("session_id") == session_id:
            return True
    return False


def _find_resumable_session_for_task(task_id: str) -> str:
    if not task_id:
        return ""

    sessions_path = BASE_DIR / CONFIG["data_paths"]["sessions"]
    sessions_data = load_json_file(sessions_path, {})
    if not isinstance(sessions_data, dict):
        return ""

    candidates: list[tuple[str, str]] = []
    for session_id, payload in sessions_data.items():
        if not isinstance(payload, dict):
            continue
        if payload.get("schedule_task_id") != task_id:
            continue
        if payload.get("trigger_source") != "schedule":
            continue
        if payload.get("status") not in {"running", "stopped", "failed", "recovered"}:
            continue
        if _is_session_deleted(session_id):
            continue

        sort_key = payload.get("start_time") or ""
        candidates.append((sort_key, session_id))

    if not candidates:
        return ""

    candidates.sort(reverse=True)
    return candidates[0][1]


def _status_payload() -> Dict[str, Any]:
    with state_lock:
        running = active_session is not None
        current = active_session
        has_task_payload = last_task_payload is not None
    return {
        "running": running,
        "session": current,
        "can_start_manual": (not running) and has_task_payload,
        "has_task_payload": has_task_payload,
    }


def _emit_log(level: str, message: str) -> None:
    payload = {
        "timestamp": local_now_text(),
        "level": level,
        "message": message,
    }
    socketio.emit("log_event", payload)


def _build_history_stub(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "session_id": payload["session_id"],
        "test_name": payload["test_name"],
        "protocol": payload["protocol"],
        "host": payload["host"],
        "port": payload["port"],
        "start_time": payload["start_time"],
        "status": "running",
        "sampling_interval_seconds": payload["sampling_interval_seconds"],
        "auto_stop_minutes": payload["auto_stop_minutes"],
        "description": payload.get("description", ""),
        "weather": payload.get("weather", ""),
    }


def _runtime_summary(session_payload: Dict[str, Any]) -> Dict[str, Any]:
    metrics = session_payload.get("metrics", [])
    ping_values = [m.get("ping_ms", 0.0) for m in metrics if m.get("ping_ms", 0.0) > 0]
    throughput_values = [m.get("throughput_mbps", 0.0) for m in metrics if m.get("throughput_mbps", 0.0) > 0]
    jitter_values = [m.get("jitter_ms", 0.0) for m in metrics if m.get("jitter_ms", 0.0) > 0]

    return {
        "average_throughput": round(sum(throughput_values) / len(throughput_values), 3) if throughput_values else 0.0,
        "max_throughput": round(max(throughput_values), 3) if throughput_values else 0.0,
        "average_jitter": round(sum(jitter_values) / len(jitter_values), 3) if jitter_values else 0.0,
        "average_ping": round(sum(ping_values) / len(ping_values), 3) if ping_values else 0.0,
        "total_packet_loss": round(sum(m.get("packet_loss_percent", 0.0) for m in metrics), 3),
        "total_transfer_mb": round(sum(m.get("transfer_mb", 0.0) for m in metrics), 3),
        "total_samples": len(metrics),
        "total_lost_datagrams": int(sum(m.get("lost_datagrams", 0) for m in metrics)),
        "total_datagrams": int(sum(m.get("total_datagrams", 0) for m in metrics)),
        "total_retransmits": int(sum(m.get("retransmits", 0) for m in metrics)),
        "test_duration_seconds": round(metrics[-1].get("interval_end", 0.0), 3) if metrics else 0.0,
        "end_time": local_now_text(),
    }


def _collect_export_logs(history_records: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    output: list[Dict[str, Any]] = []
    for item in history_records:
        session_id = item.get("session_id")
        if not session_id:
            continue
        session_data = session_manager.get_session(session_id)
        if not session_data:
            continue

        metrics = session_data.get("metrics", [])
        for metric in metrics:
            output.append(
                {
                    "session_id": session_id,
                    "test_name": session_data.get("test_name", ""),
                    "protocol": session_data.get("protocol", ""),
                    "host": session_data.get("host", ""),
                    "port": session_data.get("port", ""),
                    "timestamp": metric.get("timestamp", ""),
                    "interval_end": metric.get("interval_end", 0.0),
                    "throughput_mbps": metric.get("throughput_mbps", 0.0),
                    "transfer_mb": metric.get("transfer_mb", 0.0),
                    "jitter_ms": metric.get("jitter_ms", 0.0),
                    "packet_loss_percent": metric.get("packet_loss_percent", 0.0),
                    "lost_datagrams": metric.get("lost_datagrams", 0),
                    "total_datagrams": metric.get("total_datagrams", 0),
                    "retransmits": metric.get("retransmits", 0),
                    "ping_ms": metric.get("ping_ms", 0.0),
                    "raw": metric.get("raw", ""),
                }
            )
    return output


def _load_jsonl_records() -> list[Dict[str, Any]]:
    path = BASE_DIR / CONFIG["log_paths"]["jsonl"]
    if not path.exists():
        return []

    output: list[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                output.append(parsed)
    return output


def _history_fallback_from_jsonl(existing_records: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    deleted_ids = _load_deleted_session_ids()
    existing_records = [
        item for item in existing_records if item.get("session_id") and item.get("session_id") not in deleted_ids
    ]
    existing_ids = {item.get("session_id", "") for item in existing_records if item.get("session_id")}
    jsonl_records = _load_jsonl_records()
    grouped: Dict[str, Dict[str, Any]] = {}

    for rec in jsonl_records:
        session_id = (rec.get("session_id") or "").strip()
        if not session_id or session_id in existing_ids or session_id in deleted_ids:
            continue

        timestamp = rec.get("timestamp", "")
        item = grouped.get(session_id)
        if not item:
            grouped[session_id] = {
                "session_id": session_id,
                "test_name": rec.get("test_name", "Untitled Test"),
                "protocol": rec.get("protocol", ""),
                "host": rec.get("host", ""),
                "port": rec.get("port", ""),
                "start_time": timestamp,
                "end_time": timestamp,
                "status": "recovered",
                "sampling_interval_seconds": 0,
                "description": "Recovered from JSONL logs",
                "weather": "",
            }
            continue

        if timestamp and (not item.get("start_time") or timestamp < item.get("start_time", "")):
            item["start_time"] = timestamp
        if timestamp and (not item.get("end_time") or timestamp > item.get("end_time", "")):
            item["end_time"] = timestamp

    recovered = list(grouped.values())
    merged = list(existing_records) + recovered
    merged.sort(key=lambda x: x.get("start_time", ""), reverse=True)
    return merged


def _collect_export_logs_from_jsonl(history_records: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    deleted_ids = _load_deleted_session_ids()
    session_ids = {item.get("session_id", "") for item in history_records if item.get("session_id")}
    session_ids -= deleted_ids
    if not session_ids:
        return []

    output: list[Dict[str, Any]] = []
    for rec in _load_jsonl_records():
        session_id = rec.get("session_id", "")
        if session_id not in session_ids:
            continue
        output.append(
            {
                "session_id": session_id,
                "test_name": rec.get("test_name", ""),
                "protocol": rec.get("protocol", ""),
                "host": rec.get("host", ""),
                "port": rec.get("port", ""),
                "timestamp": rec.get("timestamp", ""),
                "interval_end": rec.get("interval_end", ""),
                "throughput_mbps": rec.get("throughput_mbps", 0.0),
                "transfer_mb": rec.get("transfer_mb", 0.0),
                "jitter_ms": rec.get("jitter_ms", 0.0),
                "packet_loss_percent": rec.get("packet_loss_percent", 0.0),
                "lost_datagrams": rec.get("lost_datagrams", 0),
                "total_datagrams": rec.get("total_datagrams", 0),
                "retransmits": rec.get("retransmits", 0),
                "ping_ms": rec.get("ping_ms", 0.0),
                "raw": rec.get("raw", ""),
            }
        )
    return output


def _find_history_record(session_id: str) -> Dict[str, Any] | None:
    if _is_session_deleted(session_id):
        return None
    for item in session_manager.list_history():
        if item.get("session_id") == session_id:
            return dict(item)
    return None


def _build_recovered_session(session_id: str, base_session: Dict[str, Any] | None = None) -> Dict[str, Any] | None:
    if _is_session_deleted(session_id):
        return None

    rows = [item for item in _load_jsonl_records() if item.get("session_id") == session_id]
    if not rows:
        return base_session

    rows.sort(key=lambda x: x.get("timestamp", ""))
    history_item = _find_history_record(session_id) or {}
    recovered = dict(base_session or {})
    status_value = recovered.get("status")
    if status_value in (None, "", "running") and history_item.get("status"):
        status_value = history_item.get("status")

    first = rows[0]
    sampling_seconds = int(
        recovered.get("sampling_interval_seconds")
        or history_item.get("sampling_interval_seconds")
        or 60
    )
    sampling_seconds = max(1, sampling_seconds)

    metrics: list[Dict[str, Any]] = []
    for idx, row in enumerate(rows, start=1):
        metrics.append(
            {
                "interval_end": idx * sampling_seconds,
                "transfer_mb": float(row.get("transfer_mb", 0.0) or 0.0),
                "throughput_mbps": float(row.get("throughput_mbps", 0.0) or 0.0),
                "jitter_ms": float(row.get("jitter_ms", 0.0) or 0.0),
                "packet_loss_percent": float(row.get("packet_loss_percent", 0.0) or 0.0),
                "lost_datagrams": int(row.get("lost_datagrams", 0) or 0),
                "total_datagrams": int(row.get("total_datagrams", 0) or 0),
                "retransmits": int(row.get("retransmits", 0) or 0),
                "ping_ms": float(row.get("ping_ms", 0.0) or 0.0),
                "timestamp": row.get("timestamp", ""),
                "raw": row.get("raw", ""),
            }
        )

    recovered.update(
        {
            "session_id": session_id,
            "test_name": recovered.get("test_name") or history_item.get("test_name") or first.get("test_name", "Untitled Test"),
            "protocol": recovered.get("protocol") or history_item.get("protocol") or first.get("protocol", ""),
            "host": recovered.get("host") or history_item.get("host") or first.get("host", ""),
            "port": recovered.get("port") or history_item.get("port") or first.get("port", ""),
            "start_time": recovered.get("start_time") or history_item.get("start_time") or first.get("timestamp", ""),
            "end_time": recovered.get("end_time") or history_item.get("end_time") or rows[-1].get("timestamp", ""),
            "sampling_interval_seconds": sampling_seconds,
            "status": status_value or "recovered",
            "metrics": metrics,
        }
    )

    summary = _runtime_summary({"metrics": metrics})
    summary["end_time"] = recovered.get("end_time") or rows[-1].get("timestamp", "")
    recovered["summary"] = summary
    return recovered


def _resolve_session_with_fallback(session_id: str) -> Dict[str, Any] | None:
    if _is_session_deleted(session_id):
        return None

    session_data = session_manager.get_session(session_id)
    if session_data and session_data.get("metrics"):
        if not session_data.get("summary"):
            summary = _runtime_summary({"metrics": session_data.get("metrics", [])})
            summary["end_time"] = session_data.get("end_time") or summary.get("end_time", "")
            session_data["summary"] = summary
        return session_data

    recovered = _build_recovered_session(session_id, session_data)
    if not recovered:
        return session_data

    # Simpan hasil recovery agar request berikutnya tidak perlu rebuild dari JSONL.
    session_manager.save_session(session_id, recovered)
    return recovered


def _log_jsonl_event(session_payload: Dict[str, Any], metric: Dict[str, Any], ping_ms: float = 0.0) -> None:
    logger.write_jsonl(
        {
            "timestamp": local_now_text(),
            "session_id": session_payload["session_id"],
            "test_name": session_payload["test_name"],
            "protocol": session_payload["protocol"],
            "host": session_payload["host"],
            "throughput_mbps": metric.get("throughput_mbps", 0.0),
            "jitter_ms": metric.get("jitter_ms", 0.0),
            "packet_loss_percent": metric.get("packet_loss_percent", 0.0),
            "lost_datagrams": metric.get("lost_datagrams", 0),
            "total_datagrams": metric.get("total_datagrams", 0),
            "ping_ms": ping_ms,
            "transfer_mb": metric.get("transfer_mb", 0.0),
        }
    )


def _start_callbacks(session_payload: Dict[str, Any]):
    def on_metric(metric: Dict[str, Any], raw_line: str) -> None:
        global active_session

        with state_lock:
            if not active_session:
                return
            metric["raw"] = raw_line
            metric["timestamp"] = local_now_text()
            metric["ping_ms"] = active_session.get("last_ping", 0.0)
            active_session["metrics"].append(metric)
            session_manager.save_session(active_session["session_id"], active_session)

        live_stats.add_metric(metric.get("throughput_mbps", 0.0), metric.get("jitter_ms", 0.0), metric.get("packet_loss_percent", 0.0))
        _log_jsonl_event(session_payload, metric, metric.get("ping_ms", 0.0))

        socketio.emit("metric_update", {"metric": metric, "stats": live_stats.snapshot()})

    def on_ping(ping_ms: float, raw_line: str) -> None:
        global active_session
        with state_lock:
            if not active_session:
                return
            active_session["last_ping"] = ping_ms

        live_stats.add_ping(ping_ms)
        socketio.emit("ping_update", {"ping_ms": ping_ms, "timestamp": local_now_text()})

    def on_log(level: str, message: str) -> None:
        _emit_log(level, message)

    def on_finished(exit_code: int) -> None:
        global active_runner, active_session, live_stats

        with state_lock:
            if not active_session:
                return
            session_payload_local = active_session

        summary = _runtime_summary(session_payload_local)
        session_payload_local["summary"] = summary
        session_payload_local["status"] = "completed" if exit_code == 0 else "stopped"
        schedule_task_id = session_payload_local.get("schedule_task_id", "")

        history_update = {
            "status": session_payload_local["status"],
            "end_time": summary["end_time"],
            **summary,
        }

        session_manager.save_session(session_payload_local["session_id"], session_payload_local)
        session_manager.update_history_summary(session_payload_local["session_id"], history_update)
        if schedule_task_id:
            schedule_manager.mark_completed(schedule_task_id, session_payload_local["status"])

        socketio.emit("session_complete", {"session_id": session_payload_local["session_id"], "summary": summary})
        socketio.emit("status_update", _status_payload())

        with state_lock:
            active_runner = None
            active_session = None
            live_stats = LiveStatistics()

    return on_metric, on_ping, on_log, on_finished


def _build_session_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    protocol = readable_protocol(payload.get("protocol", "TCP"))
    defaults = CONFIG.get("defaults", {})
    limit_cfg = CONFIG.get("limits", {})

    sampling_interval = clamp(
        int(payload.get("sampling_interval", payload.get("duration", defaults[protocol.lower()]["duration"]))),
        1,
        3600,
    )
    auto_stop_minutes = clamp(int(payload.get("auto_stop_minutes", defaults.get("auto_stop_minutes", 5))), 1, 1440)
    total_duration_seconds = clamp(
        int(payload.get("total_duration_seconds", auto_stop_minutes * 60)),
        sampling_interval,
        86400,
    )
    auto_stop_minutes = max(1, (total_duration_seconds + 59) // 60)
    port = clamp(int(payload.get("port", 5201)), 1, limit_cfg.get("max_port", 65535))

    session_payload = {
        "session_id": session_manager.generate_session_id(),
        "test_name": sanitize_text(payload.get("test_name"), "Untitled Test"),
        "test_date": sanitize_text(payload.get("test_date"), local_now_text().split(" ")[0]),
        "description": sanitize_text(payload.get("description"), ""),
        "weather": sanitize_text(payload.get("weather"), ""),
        "host": sanitize_text(payload.get("host"), ""),
        "port": port,
        "protocol": protocol,
        "sampling_interval_seconds": sampling_interval,
        "auto_stop_minutes": auto_stop_minutes,
        "total_duration_seconds": total_duration_seconds,
        "ping_interval": sampling_interval,
        "status": "running",
        "start_time": local_now_text(),
        "end_time": "",
        "metrics": [],
        "last_ping": 0.0,
    }

    if protocol == "UDP":
        udp_defaults = defaults.get("udp", {})
        session_payload["bandwidth"] = sanitize_text(payload.get("bandwidth"), str(udp_defaults.get("bandwidth", "20M")))
        session_payload["packet_size"] = clamp(int(payload.get("packet_size", udp_defaults.get("packet_size", 512))), 64, limit_cfg.get("max_packet_size", 65507))
    else:
        tcp_defaults = defaults.get("tcp", {})
        session_payload["streams"] = clamp(int(payload.get("streams", tcp_defaults.get("streams", 1))), 1, limit_cfg.get("max_streams", 32))
        session_payload["mss"] = clamp(int(payload.get("mss", tcp_defaults.get("mss", 1518))), 512, 9000)

    return session_payload


def _start_test_workflow(
    payload: Dict[str, Any],
    trigger_source: str = "manual",
    schedule_task_id: str = "",
    schedule_task_name: str = "",
    resume_session_id: str = "",
):
    global active_runner, active_session, live_stats, last_task_payload

    with state_lock:
        if active_session:
            return {"ok": False, "error": "Test masih berjalan"}, 409

    requested_test_name = sanitize_text(payload.get("test_name"), "Untitled Test")
    if not resume_session_id and session_manager.test_name_exists_in_history(requested_test_name):
        return {"ok": False, "error": "Nama pengujian sudah ada di history. Gunakan nama lain."}, 400

    host = sanitize_text(payload.get("host"), "")
    if not validate_host(host):
        return {"ok": False, "error": "Host tidak valid"}, 400

    available, reason = detect_iperf_binary()
    if not available:
        return {"ok": False, "error": reason}, 400

    try:
        built_payload = _build_session_payload(payload)
    except (ValueError, TypeError):
        return {"ok": False, "error": "Parameter numerik tidak valid"}, 400

    session_payload = built_payload

    if resume_session_id:
        previous = _resolve_session_with_fallback(resume_session_id)
        if not previous:
            return {"ok": False, "error": "Session sebelumnya tidak ditemukan untuk dilanjutkan"}, 404

        session_payload = dict(previous)
        session_payload.update(
            {
                "test_name": built_payload.get("test_name"),
                "test_date": built_payload.get("test_date"),
                "description": built_payload.get("description", ""),
                "weather": built_payload.get("weather", ""),
                "host": built_payload.get("host"),
                "port": built_payload.get("port"),
                "protocol": built_payload.get("protocol"),
                "sampling_interval_seconds": built_payload.get("sampling_interval_seconds"),
                "auto_stop_minutes": built_payload.get("auto_stop_minutes"),
                "total_duration_seconds": built_payload.get("total_duration_seconds"),
                "ping_interval": built_payload.get("sampling_interval_seconds"),
                "status": "running",
                "end_time": "",
                "last_ping": 0.0,
            }
        )
        session_payload.setdefault("metrics", [])
        session_payload.pop("summary", None)

        if session_payload.get("protocol") == "UDP":
            session_payload["bandwidth"] = built_payload.get("bandwidth", session_payload.get("bandwidth", "20M"))
            session_payload["packet_size"] = built_payload.get("packet_size", session_payload.get("packet_size", 512))
            session_payload.pop("streams", None)
            session_payload.pop("mss", None)
        else:
            session_payload["streams"] = built_payload.get("streams", session_payload.get("streams", 1))
            session_payload["mss"] = built_payload.get("mss", session_payload.get("mss", 1518))
            session_payload.pop("bandwidth", None)
            session_payload.pop("packet_size", None)

    with state_lock:
        last_task_payload = dict(payload)

    session_payload["trigger_source"] = trigger_source
    if schedule_task_id:
        session_payload["schedule_task_id"] = schedule_task_id
    if schedule_task_name:
        session_payload["schedule_task_name"] = schedule_task_name
    schedule_end_at = sanitize_text(payload.get("schedule_end_at"), "")
    if schedule_end_at:
        session_payload["schedule_end_at"] = schedule_end_at

    on_metric, on_ping, on_log, on_finished = _start_callbacks(session_payload)

    runner = IperfTestRunner(
        session_payload=session_payload,
        on_metric=on_metric,
        on_ping=on_ping,
        on_log=on_log,
        on_finished=on_finished,
    )

    with state_lock:
        active_session = session_payload
        active_runner = runner
        live_stats = LiveStatistics()

    session_manager.save_session(session_payload["session_id"], session_payload)
    if resume_session_id:
        session_manager.update_history_summary(
            session_payload["session_id"],
            {
                "status": "running",
                "end_time": "",
                "updated_at": local_now_text(),
            },
        )
    else:
        session_manager.append_history(_build_history_stub(session_payload))

    action = "resumed" if resume_session_id else "started"
    logger.info(f"Session {action}: {session_payload['session_id']} ({trigger_source})")
    _emit_log("system", f"Session {session_payload['session_id']} {action} via {trigger_source}")

    runner.start()
    socketio.emit("status_update", _status_payload())
    return {"ok": True, "session": session_payload}, 200


def _scheduler_loop() -> None:
    while not scheduler_stop_event.is_set():
        now_dt = datetime.now()

        expired_items = schedule_manager.expired_pending_tasks(now_dt)
        for task in expired_items:
            schedule_manager.mark_failed(task.get("id", ""), "Rentang jadwal terlewati sebelum task sempat dijalankan")
            socketio.emit("schedule_update", {"task_id": task.get("id", ""), "status": "failed"})

        due_items = schedule_manager.due_tasks(now_dt)
        for task in due_items:
            with state_lock:
                busy = active_session is not None
            if busy:
                continue

            try:
                end_dt = datetime.fromisoformat(task.get("end_at", ""))
            except ValueError:
                schedule_manager.mark_failed(task.get("id", ""), "Rentang jadwal tidak valid")
                socketio.emit("schedule_update", {"task_id": task.get("id", ""), "status": "failed"})
                continue

            remaining_seconds = max(1, int((end_dt - datetime.now()).total_seconds()))
            task_payload = dict(task.get("payload", {}))
            task_payload["total_duration_seconds"] = remaining_seconds
            task_payload["schedule_end_at"] = task.get("end_at", "")
            if not task_payload.get("test_date"):
                task_payload["test_date"] = (task.get("start_at") or "").split("T")[0]
            resumable_session_id = _find_resumable_session_for_task(task.get("id", ""))

            schedule_manager.mark_running(task["id"])
            response, status = _start_test_workflow(
                task_payload,
                trigger_source="schedule",
                schedule_task_id=task.get("id", ""),
                schedule_task_name=task.get("task_name", "Scheduled Task"),
                resume_session_id=resumable_session_id,
            )
            if status >= 400:
                schedule_manager.mark_failed(task["id"], response.get("error", "Gagal mengeksekusi task"))
            socketio.emit("schedule_update", {"task_id": task.get("id", ""), "status": "running" if status < 400 else "failed"})

        scheduler_stop_event.wait(1)


def _start_scheduler_thread() -> None:
    global scheduler_thread
    if scheduler_thread and scheduler_thread.is_alive():
        return
    scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True)
    scheduler_thread.start()


def _recover_scheduler_tasks_on_startup() -> None:
    recovered = schedule_manager.recover_running_tasks_on_startup(datetime.now())
    if recovered:
        logger.info(f"Recovered {len(recovered)} running task(s) after restart")


@app.context_processor
def inject_brand():
    return {"brand": CONFIG.get("brand", {})}


@app.route("/")
def index():
    return render_template("index.html", config=CONFIG)


@app.route("/schedule")
def schedule_page():
    return render_template("schedule.html", config=CONFIG)


@app.route("/history")
def history_page():
    return render_template("history.html")


@app.route("/report/<session_id>")
def report_page(session_id: str):
    session_data = _resolve_session_with_fallback(session_id)
    if not session_data:
        return render_template("report.html", session=None, summary=None)
    return render_template("report.html", session=session_data, summary=session_data.get("summary", {}))


@app.route("/api/status")
def api_status():
    available, iperf_path = detect_iperf_binary()
    status = _status_payload()
    current = status["session"]
    return jsonify(
        {
            **status,
            "session": current,
            "iperf_available": available,
            "iperf_binary": iperf_path,
            "running_task": {
                "source": (current or {}).get("trigger_source", ""),
                "name": (current or {}).get("schedule_task_name") or (current or {}).get("test_name", "-"),
                "schedule_task_id": (current or {}).get("schedule_task_id", ""),
            },
        }
    )


@app.route("/api/test/start", methods=["POST"])
def api_start_test():
    payload = request.get_json(force=True, silent=True) or {}
    response, status = _start_test_workflow(payload, trigger_source="manual")
    return jsonify(response), status


@app.route("/api/test/start-last", methods=["POST"])
def api_start_last_test():
    with state_lock:
        payload = dict(last_task_payload) if last_task_payload else None

    if not payload:
        return jsonify({"ok": False, "error": "Belum ada task manual yang bisa dijalankan"}), 404

    response, status = _start_test_workflow(payload, trigger_source="manual")
    return jsonify(response), status


@app.route("/api/test/stop", methods=["POST"])
def api_stop_test():
    global active_runner

    with state_lock:
        runner = active_runner

    if not runner:
        return jsonify({"ok": False, "error": "Tidak ada test yang berjalan"}), 404

    runner.stop()
    _emit_log("system", "Stop command requested by user")
    return jsonify({"ok": True})


@app.route("/api/logs/clear", methods=["POST"])
def api_clear_logs():
    (BASE_DIR / CONFIG["log_paths"]["runtime"]).write_text("", encoding="utf-8")
    (BASE_DIR / CONFIG["log_paths"]["error"]).write_text("", encoding="utf-8")
    return jsonify({"ok": True})


@app.route("/api/history")
def api_history():
    records = _history_fallback_from_jsonl(session_manager.list_history())
    protocol = request.args.get("protocol", "")
    test_name = request.args.get("test_name", "")
    host = request.args.get("host", "")
    date = request.args.get("date", "")
    session_id = request.args.get("session_id", "")

    filtered = apply_filters(
        records,
        {
            "protocol": protocol,
            "test_name": test_name,
            "host": host,
            "date": date,
            "session_id": session_id,
        },
    )
    return jsonify({"ok": True, "records": filtered})


@app.route("/api/session/<session_id>")
def api_session_detail(session_id: str):
    session_data = _resolve_session_with_fallback(session_id)
    if not session_data:
        return jsonify({"ok": False, "error": "Session tidak ditemukan"}), 404
    return jsonify({"ok": True, "session": session_data})


@app.route("/api/session/<session_id>", methods=["DELETE"])
def api_delete_session(session_id: str):
    deleted_session = session_manager.delete_session(session_id)
    deleted_history = session_manager.delete_history_item(session_id)
    exists_in_jsonl = _session_exists_in_jsonl(session_id)

    if not deleted_session and not deleted_history and not exists_in_jsonl and not _is_session_deleted(session_id):
        return jsonify({"ok": False, "error": "Session tidak ditemukan"}), 404

    _mark_session_deleted(session_id)
    return jsonify({"ok": True})


@app.route("/api/schedules", methods=["GET"])
def api_list_schedules():
    return jsonify({"ok": True, "tasks": schedule_manager.list_tasks()})


@app.route("/api/schedules", methods=["POST"])
def api_create_schedule():
    payload = request.get_json(force=True, silent=True) or {}
    task_name = sanitize_text(payload.get("task_name"), "Scheduled Task")
    start_at = sanitize_text(payload.get("start_at", payload.get("scheduled_at")), "")
    end_at = sanitize_text(payload.get("end_at"), "")
    task_payload = payload.get("payload", {})
    requested_test_name = sanitize_text(task_payload.get("test_name"), "Untitled Test")

    if session_manager.test_name_exists_in_history(task_name):
        return jsonify({"ok": False, "error": "Nama task sudah ada di history. Gunakan nama lain."}), 400
    if session_manager.test_name_exists_in_history(requested_test_name):
        return jsonify({"ok": False, "error": "Nama pengujian sudah ada di history. Gunakan nama lain."}), 400

    try:
        start_dt = datetime.fromisoformat(start_at)
        end_dt = datetime.fromisoformat(end_at)
    except ValueError:
        return jsonify({"ok": False, "error": "Format rentang tanggal/jam tidak valid"}), 400

    if end_dt <= start_dt:
        return jsonify({"ok": False, "error": "Waktu selesai harus lebih besar dari waktu mulai"}), 400

    if end_dt < datetime.now():
        return jsonify({"ok": False, "error": "Rentang jadwal sudah lewat"}), 400

    overlap = schedule_manager.find_overlapping_task(start_at, end_at)
    if overlap:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": f"Rentang jadwal bentrok dengan task '{overlap.get('task_name', '-')}' ({overlap.get('start_at', '-')} - {overlap.get('end_at', '-')})",
                }
            ),
            400,
        )

    created = schedule_manager.create_task({"task_name": task_name, "start_at": start_at, "end_at": end_at, "payload": task_payload})
    return jsonify({"ok": True, "task": created})


@app.route("/api/schedules/<task_id>", methods=["PUT"])
def api_update_schedule(task_id: str):
    payload = request.get_json(force=True, silent=True) or {}
    task_name = sanitize_text(payload.get("task_name"), "Scheduled Task")
    start_at = sanitize_text(payload.get("start_at", payload.get("scheduled_at")), "")
    end_at = sanitize_text(payload.get("end_at"), "")
    task_payload = payload.get("payload", {})
    requested_test_name = sanitize_text(task_payload.get("test_name"), "Untitled Test")

    if session_manager.test_name_exists_in_history(task_name):
        return jsonify({"ok": False, "error": "Nama task sudah ada di history. Gunakan nama lain."}), 400
    if session_manager.test_name_exists_in_history(requested_test_name):
        return jsonify({"ok": False, "error": "Nama pengujian sudah ada di history. Gunakan nama lain."}), 400

    try:
        start_dt = datetime.fromisoformat(start_at)
        end_dt = datetime.fromisoformat(end_at)
    except ValueError:
        return jsonify({"ok": False, "error": "Format rentang tanggal/jam tidak valid"}), 400

    if end_dt <= start_dt:
        return jsonify({"ok": False, "error": "Waktu selesai harus lebih besar dari waktu mulai"}), 400

    overlap = schedule_manager.find_overlapping_task(start_at, end_at, exclude_task_id=task_id)
    if overlap:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": f"Rentang jadwal bentrok dengan task '{overlap.get('task_name', '-')}' ({overlap.get('start_at', '-')} - {overlap.get('end_at', '-')})",
                }
            ),
            400,
        )

    updated = schedule_manager.update_task(task_id, {"task_name": task_name, "start_at": start_at, "end_at": end_at, "payload": task_payload})
    if not updated:
        return jsonify({"ok": False, "error": "Task tidak ditemukan atau sedang berjalan"}), 404
    return jsonify({"ok": True, "task": updated})


@app.route("/api/schedules/<task_id>", methods=["DELETE"])
def api_delete_schedule(task_id: str):
    task = schedule_manager.get_task(task_id)
    if not task:
        return jsonify({"ok": False, "error": "Task tidak ditemukan"}), 404

    should_stop = False
    with state_lock:
        should_stop = bool(active_session and active_session.get("schedule_task_id") == task_id and active_runner)
        runner = active_runner if should_stop else None

    if runner:
        runner.stop()
        _emit_log("system", f"Task {task_id} dihentikan karena task dihapus")

    ok = schedule_manager.delete_task(task_id)
    if not ok:
        return jsonify({"ok": False, "error": "Task tidak ditemukan"}), 404
    return jsonify({"ok": True})


@app.route("/api/export")
def api_export():
    records = _history_fallback_from_jsonl(session_manager.list_history())
    filtered = apply_filters(
        records,
        {
            "protocol": request.args.get("protocol", ""),
            "test_name": request.args.get("test_name", ""),
            "host": request.args.get("host", ""),
            "date": request.args.get("date", ""),
            "session_id": request.args.get("session_id", ""),
        },
    )
    export_logs = _collect_export_logs(filtered)
    jsonl_logs = _collect_export_logs_from_jsonl(filtered)
    if jsonl_logs:
        seen = {
            (
                item.get("session_id", ""),
                item.get("timestamp", ""),
                item.get("throughput_mbps", 0.0),
                item.get("transfer_mb", 0.0),
            )
            for item in export_logs
        }
        for item in jsonl_logs:
            key = (
                item.get("session_id", ""),
                item.get("timestamp", ""),
                item.get("throughput_mbps", 0.0),
                item.get("transfer_mb", 0.0),
            )
            if key not in seen:
                export_logs.append(item)
                seen.add(key)

    fmt = (request.args.get("format") or "json").lower()
    if fmt == "jsonl":
        body = export_jsonl(filtered, export_logs)
        mime = "application/x-ndjson"
        filename = export_filename("history", "jsonl")
    elif fmt == "csv":
        body = export_csv(filtered, export_logs)
        mime = "text/csv"
        filename = export_filename("history", "csv")
    elif fmt == "xlsx":
        try:
            body = export_excel(filtered, export_logs)
        except RuntimeError as err:
            return jsonify({"ok": False, "error": str(err)}), 500
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = export_filename("history", "xlsx")
    else:
        body = export_json(filtered, export_logs)
        mime = "application/json"
        filename = export_filename("history", "json")

    response = Response(body, mimetype=mime)
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response


@socketio.on("connect")
def on_connect():
    socketio.emit("status_update", _status_payload())


_recover_scheduler_tasks_on_startup()
_start_scheduler_thread()


if __name__ == "__main__":
    socketio.run(app, host=CONFIG.get("host", "0.0.0.0"), port=CONFIG.get("port", 5000), debug=False)
