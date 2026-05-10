import json
import threading
from pathlib import Path
from typing import Any, Dict

from flask import Flask, Response, jsonify, render_template, request
from flask_socketio import SocketIO

from modules.exporter import apply_filters, export_csv, export_excel, export_filename, export_json, export_jsonl
from modules.iperf_runner import IperfTestRunner
from modules.logger import AppLogger
from modules.session_manager import SessionManager
from modules.statistics import LiveStatistics
from modules.utils import (
    clamp,
    detect_iperf_binary,
    ensure_project_paths,
    local_now_text,
    read_config,
    readable_protocol,
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

state_lock = threading.Lock()
active_runner: IperfTestRunner | None = None
active_session: Dict[str, Any] | None = None
live_stats = LiveStatistics()


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

        history_update = {
            "status": session_payload_local["status"],
            "end_time": summary["end_time"],
            **summary,
        }

        session_manager.save_session(session_payload_local["session_id"], session_payload_local)
        session_manager.update_history_summary(session_payload_local["session_id"], history_update)

        socketio.emit("session_complete", {"session_id": session_payload_local["session_id"], "summary": summary})
        socketio.emit("status_update", {"running": False, "session": session_payload_local})

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
    total_duration_seconds = auto_stop_minutes * 60
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


@app.context_processor
def inject_brand():
    return {"brand": CONFIG.get("brand", {})}


@app.route("/")
def index():
    return render_template("index.html", config=CONFIG)


@app.route("/history")
def history_page():
    return render_template("history.html")


@app.route("/report/<session_id>")
def report_page(session_id: str):
    session_data = session_manager.get_session(session_id)
    if not session_data:
        return render_template("report.html", session=None, summary=None)
    return render_template("report.html", session=session_data, summary=session_data.get("summary", {}))


@app.route("/api/status")
def api_status():
    available, iperf_path = detect_iperf_binary()
    with state_lock:
        running = active_session is not None
        current = active_session
    return jsonify({"running": running, "session": current, "iperf_available": available, "iperf_binary": iperf_path})


@app.route("/api/test/start", methods=["POST"])
def api_start_test():
    global active_runner, active_session, live_stats

    payload = request.get_json(force=True, silent=True) or {}

    with state_lock:
        if active_session:
            return jsonify({"ok": False, "error": "Test masih berjalan"}), 409

    host = sanitize_text(payload.get("host"), "")
    if not validate_host(host):
        return jsonify({"ok": False, "error": "Host tidak valid"}), 400

    available, reason = detect_iperf_binary()
    if not available:
        return jsonify({"ok": False, "error": reason}), 400

    try:
        session_payload = _build_session_payload(payload)
    except (ValueError, TypeError):
        return jsonify({"ok": False, "error": "Parameter numerik tidak valid"}), 400

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
    session_manager.append_history(_build_history_stub(session_payload))

    logger.info(f"Session started: {session_payload['session_id']}")
    _emit_log("system", f"Session {session_payload['session_id']} started")

    runner.start()
    socketio.emit("status_update", {"running": True, "session": session_payload})

    return jsonify({"ok": True, "session": session_payload})


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
    records = session_manager.list_history()
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
    session_data = session_manager.get_session(session_id)
    if not session_data:
        return jsonify({"ok": False, "error": "Session tidak ditemukan"}), 404
    return jsonify({"ok": True, "session": session_data})


@app.route("/api/session/<session_id>", methods=["DELETE"])
def api_delete_session(session_id: str):
    deleted_session = session_manager.delete_session(session_id)
    deleted_history = session_manager.delete_history_item(session_id)
    if not deleted_session and not deleted_history:
        return jsonify({"ok": False, "error": "Session tidak ditemukan"}), 404
    return jsonify({"ok": True})


@app.route("/api/export")
def api_export():
    records = session_manager.list_history()
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
    socketio.emit("status_update", {"running": active_session is not None, "session": active_session})


if __name__ == "__main__":
    socketio.run(app, host=CONFIG.get("host", "0.0.0.0"), port=CONFIG.get("port", 5000), debug=False)
