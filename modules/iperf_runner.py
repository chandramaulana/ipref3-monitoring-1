import subprocess
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from modules.parser import parse_iperf_line
from modules.parser import parse_ping_line
from modules.utils import build_ping_command


class IperfTestRunner:
    def __init__(
        self,
        session_payload: Dict[str, Any],
        on_metric: Callable[[Dict[str, Any], str], None],
        on_ping: Callable[[float, str], None],
        on_log: Callable[[str, str], None],
        on_finished: Callable[[int], None],
    ):
        self.session_payload = session_payload
        self.protocol = session_payload.get("protocol", "TCP").upper()
        self.on_metric = on_metric
        self.on_ping = on_ping
        self.on_log = on_log
        self.on_finished = on_finished
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._proc: Optional[subprocess.Popen] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
        if self._thread and self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=3)

    def _build_command(self):
        host = self.session_payload["host"]
        port = str(self.session_payload["port"])
        sample_duration = str(self.session_payload.get("sampling_interval_seconds", 1))
        sampling_interval = str(self.session_payload.get("sampling_interval_seconds", 1))

        command = ["iperf3", "-c", host, "-p", port, "-i", sampling_interval, "-t", sample_duration]

        if self.protocol == "UDP":
            command.extend([
                "-u",
                "-b",
                self.session_payload.get("bandwidth", "20M"),
                "-l",
                str(self.session_payload.get("packet_size", 512)),
            ])
        else:
            streams = str(self.session_payload.get("streams", 1))
            mss = str(self.session_payload.get("mss", 1460))
            command.extend(["-P", streams, "-M", mss])

        return command

    def _run_ping_once(self) -> Optional[float]:
        command = build_ping_command(self.session_payload["host"])
        try:
            proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as err:
            self.on_log("error", f"Ping gagal dijalankan: {err}")
            return None

        ping_value: Optional[float] = None
        assert proc.stdout is not None
        for line in proc.stdout:
            if self._stop_event.is_set():
                break
            cleaned = line.strip()
            if not cleaned:
                continue
            self.on_log("ping", cleaned)
            parsed = parse_ping_line(cleaned)
            if parsed is not None:
                ping_value = parsed

        if proc.poll() is None:
            proc.terminate()
        return ping_value

    def _run(self) -> None:
        sample_seconds = max(1, int(self.session_payload.get("sampling_interval_seconds", 1)))
        total_seconds = max(sample_seconds, int(self.session_payload.get("total_duration_seconds", 60)))
        max_cycles = max(1, (total_seconds + sample_seconds - 1) // sample_seconds)
        schedule_end_at = self.session_payload.get("schedule_end_at", "")
        schedule_end_dt: Optional[datetime] = None
        if schedule_end_at:
            try:
                schedule_end_dt = datetime.fromisoformat(schedule_end_at)
                remaining = max(1.0, (schedule_end_dt - datetime.now()).total_seconds())
                max_cycles = max(1, int((remaining + sample_seconds - 1) // sample_seconds))
            except ValueError:
                schedule_end_dt = None

        elapsed = 0
        exit_code = 0
        cycle = 0

        while True:
            if self._stop_event.is_set():
                break

            if schedule_end_dt and datetime.now() >= schedule_end_dt:
                break

            cycle += 1

            command = self._build_command()
            self.on_log("system", f"Cycle {cycle}/{max_cycles}: {' '.join(command)}")

            try:
                self._proc = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                )
            except OSError as err:
                self.on_log("error", f"iPerf gagal dijalankan: {err}")
                if self._stop_event.wait(timeout=sample_seconds):
                    break
                continue

            last_metric: Optional[Dict[str, Any]] = None
            last_raw = ""
            assert self._proc.stdout is not None
            for line in self._proc.stdout:
                if self._stop_event.is_set():
                    break

                cleaned = line.strip()
                if not cleaned:
                    continue

                self.on_log("iperf", cleaned)
                parsed = parse_iperf_line(cleaned, self.protocol)
                if parsed:
                    last_metric = parsed
                    last_raw = cleaned

            time.sleep(0.05)
            local_code = self._proc.poll() if self._proc else -1
            if local_code not in (0, None):
                self.on_log(
                    "error",
                    f"iPerf cycle {cycle} gagal (exit={local_code}). Scheduler tetap berjalan hingga jadwal selesai atau task dihapus.",
                )

                ping_value = self._run_ping_once()
                if ping_value is not None:
                    self.on_ping(ping_value, f"ping={ping_value} ms")

                if self._stop_event.wait(timeout=sample_seconds):
                    break
                continue

            elapsed += sample_seconds
            if last_metric:
                last_metric["interval_end"] = elapsed
                self.on_metric(last_metric, last_raw)

            ping_value = self._run_ping_once()
            if ping_value is not None:
                self.on_ping(ping_value, f"ping={ping_value} ms")

            if not schedule_end_dt and cycle >= max_cycles:
                break

        if self._stop_event.is_set() and exit_code in (0, None):
            exit_code = 130

        self.on_finished(0 if exit_code in (0, None) else exit_code)
