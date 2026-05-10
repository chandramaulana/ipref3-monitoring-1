import subprocess
import threading
import time
from typing import Callable, Optional

from modules.parser import parse_ping_line
from modules.utils import build_ping_command


class PingMonitor:
    def __init__(self, host: str, interval: int, on_ping: Callable[[float, str], None], on_log: Callable[[str, str], None]):
        self.host = host
        self.interval = interval
        self.on_ping = on_ping
        self.on_log = on_log
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._proc: Optional[subprocess.Popen] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            command = build_ping_command(self.host)
            self._proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )

            assert self._proc.stdout is not None
            for line in self._proc.stdout:
                if self._stop_event.is_set():
                    break
                cleaned = line.strip()
                if not cleaned:
                    continue

                self.on_log("ping", cleaned)
                ping = parse_ping_line(cleaned)
                if ping is not None:
                    self.on_ping(ping, cleaned)

            if self._proc and self._proc.poll() is None:
                self._proc.terminate()

            if self._stop_event.wait(timeout=max(1, self.interval)):
                break

            time.sleep(0.05)

    def stop(self) -> None:
        self._stop_event.set()
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
        if self._thread and self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=2)
