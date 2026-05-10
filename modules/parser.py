import re
from typing import Any, Dict, Optional

from modules.utils import safe_float, safe_int


IPERF_INTERVAL_PATTERN = re.compile(
    r"(?P<interval>\d+(?:\.\d+)?)-\s*(?P<end>\d+(?:\.\d+)?)\s*sec\s+"
    r"(?P<transfer>[\d.]+)\s*(?P<transfer_unit>[KMG]?Bytes?)\s+"
    r"(?P<bitrate>[\d.]+)\s*(?P<bitrate_unit>[KMG]?bits/sec)",
    re.IGNORECASE,
)

UDP_EXTRA_PATTERN = re.compile(
    r"(?P<jitter>[\d.]+)\s*ms\s+(?P<lost>\d+)\/(?P<total>\d+)\s*\((?P<loss_pct>[\d.]+)%\)",
    re.IGNORECASE,
)

RETRANS_PATTERN = re.compile(r"\s(?P<retrans>\d+)\s*$")
SENDER_RECEIVER_PATTERN = re.compile(r"\b(sender|receiver)\b", re.IGNORECASE)
PING_PATTERN = re.compile(
    r"(?:time|tempo)[=<]\s*(?P<ping>[\d.]+)\s*ms",
    re.IGNORECASE,
)


def _to_mbps(value: float, unit: str) -> float:
    unit = unit.lower()
    if unit.startswith("k"):
        return value / 1000.0
    if unit.startswith("g"):
        return value * 1000.0
    return value


def _to_mbytes(value: float, unit: str) -> float:
    unit = unit.lower()
    if unit.startswith("k"):
        return value / 1024.0
    if unit.startswith("g"):
        return value * 1024.0
    return value


def parse_iperf_line(line: str, protocol: str) -> Optional[Dict[str, Any]]:
    if "sec" not in line:
        return None

    match = IPERF_INTERVAL_PATTERN.search(line)
    if not match:
        return None

    transfer_value = safe_float(match.group("transfer"))
    transfer_unit = match.group("transfer_unit")
    bitrate_value = safe_float(match.group("bitrate"))
    bitrate_unit = match.group("bitrate_unit")

    payload: Dict[str, Any] = {
        "interval_end": safe_float(match.group("end")),
        "transfer_mb": round(_to_mbytes(transfer_value, transfer_unit), 3),
        "throughput_mbps": round(_to_mbps(bitrate_value, bitrate_unit), 3),
        "jitter_ms": 0.0,
        "packet_loss_percent": 0.0,
        "lost_datagrams": 0,
        "total_datagrams": 0,
        "retransmits": 0,
    }

    sr_match = SENDER_RECEIVER_PATTERN.search(line)
    if sr_match:
        payload["direction"] = sr_match.group(1).lower()

    if protocol.upper() == "UDP":
        udp_match = UDP_EXTRA_PATTERN.search(line)
        if udp_match:
            payload.update(
                {
                    "jitter_ms": round(safe_float(udp_match.group("jitter")), 3),
                    "packet_loss_percent": round(safe_float(udp_match.group("loss_pct")), 3),
                    "lost_datagrams": safe_int(udp_match.group("lost")),
                    "total_datagrams": safe_int(udp_match.group("total")),
                }
            )
    else:
        ret_match = RETRANS_PATTERN.search(line)
        if ret_match:
            payload["retransmits"] = safe_int(ret_match.group("retrans"))

    return payload


def parse_ping_line(line: str) -> Optional[float]:
    match = PING_PATTERN.search(line)
    if not match:
        return None
    return round(safe_float(match.group("ping")), 3)
