import csv
import io
import json
from datetime import datetime
from typing import Any, Dict, List, Optional


def apply_filters(records: List[Dict[str, Any]], filters: Dict[str, str]) -> List[Dict[str, Any]]:
    protocol = (filters.get("protocol") or "").upper()
    test_name = (filters.get("test_name") or "").strip().lower()
    host = (filters.get("host") or "").strip().lower()
    date_str = (filters.get("date") or "").strip()
    session_id = (filters.get("session_id") or "").strip().upper()

    output = []
    for rec in records:
        if protocol and rec.get("protocol", "").upper() != protocol:
            continue
        if test_name and test_name not in rec.get("test_name", "").lower():
            continue
        if host and host not in rec.get("host", "").lower():
            continue
        if session_id and rec.get("session_id", "").upper() != session_id:
            continue
        if date_str:
            start_time = rec.get("start_time", "")
            if not start_time.startswith(date_str):
                continue
        output.append(rec)
    return output


def export_json(records: List[Dict[str, Any]], log_records: Optional[List[Dict[str, Any]]] = None) -> str:
    if log_records:
        payload = {"history": records, "logs": log_records}
        return json.dumps(payload, indent=2, ensure_ascii=False)
    return json.dumps(records, indent=2, ensure_ascii=False)


def export_jsonl(records: List[Dict[str, Any]], log_records: Optional[List[Dict[str, Any]]] = None) -> str:
    source = log_records if log_records else records
    return "\n".join(json.dumps(item, ensure_ascii=False) for item in source)


def export_csv(records: List[Dict[str, Any]], log_records: Optional[List[Dict[str, Any]]] = None) -> str:
    source = log_records if log_records else records
    if not source:
        return ""

    all_keys = sorted(set().union(*[item.keys() for item in source]))
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=all_keys)
    writer.writeheader()
    writer.writerows(source)
    return buffer.getvalue()


def export_excel(records: List[Dict[str, Any]], log_records: Optional[List[Dict[str, Any]]] = None) -> bytes:
    try:
        from openpyxl import Workbook
    except ImportError as exc:
        raise RuntimeError("openpyxl belum terpasang. Jalankan pip install -r requirements.txt") from exc

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "History"

    if not records:
        sheet.append(["No Data"])
    else:
        all_keys = sorted(set().union(*[item.keys() for item in records]))
        sheet.append(all_keys)
        for row in records:
            sheet.append([row.get(k, "") for k in all_keys])

    if log_records:
        log_sheet = workbook.create_sheet("Logs")
        log_keys = sorted(set().union(*[item.keys() for item in log_records]))
        log_sheet.append(log_keys)
        for row in log_records:
            log_sheet.append([row.get(k, "") for k in log_keys])

    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    return output.getvalue()


def export_filename(prefix: str, extension: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{stamp}.{extension}"
