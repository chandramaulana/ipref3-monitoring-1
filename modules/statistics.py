from dataclasses import dataclass, field
from typing import Dict, List

from modules.utils import rolling_average


@dataclass
class LiveStatistics:
    throughput_values: List[float] = field(default_factory=list)
    jitter_values: List[float] = field(default_factory=list)
    packet_loss_values: List[float] = field(default_factory=list)
    ping_values: List[float] = field(default_factory=list)

    def add_metric(self, throughput: float, jitter: float, packet_loss: float) -> None:
        if throughput > 0:
            self.throughput_values.append(throughput)
        if jitter >= 0:
            self.jitter_values.append(jitter)
        if packet_loss >= 0:
            self.packet_loss_values.append(packet_loss)

    def add_ping(self, ping_ms: float) -> None:
        if ping_ms > 0:
            self.ping_values.append(ping_ms)

    def snapshot(self) -> Dict[str, float]:
        current_throughput = self.throughput_values[-1] if self.throughput_values else 0.0
        current_jitter = self.jitter_values[-1] if self.jitter_values else 0.0
        current_packet_loss = self.packet_loss_values[-1] if self.packet_loss_values else 0.0
        current_ping = self.ping_values[-1] if self.ping_values else 0.0

        return {
            "current_throughput": round(current_throughput, 3),
            "average_throughput": rolling_average(self.throughput_values),
            "max_throughput": round(max(self.throughput_values), 3) if self.throughput_values else 0.0,
            "current_jitter": round(current_jitter, 3),
            "average_jitter": rolling_average(self.jitter_values),
            "current_packet_loss": round(current_packet_loss, 3),
            "average_packet_loss": rolling_average(self.packet_loss_values),
            "current_ping": round(current_ping, 3),
            "average_ping": rolling_average(self.ping_values),
        }
