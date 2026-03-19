from typing import Dict, Any

def _normalize_datetime(value: Any, is_end: bool) -> Any:
    if not value:
        return None

    v = str(value).strip()
    if not v:
        return None

    # 统一 T / Z 格式
    v = v.replace("T", " ")
    if v.endswith("Z"):
        v = v[:-1]

    # 去掉时区偏移部分（如 2025-12-31 00:00:00+08:00）
    if " " in v:
        date_part, time_part = v.split(" ", 1)
        for sep in ["+", "-"]:
            if sep in time_part[1:]:
                time_part = time_part.split(sep)[0]
                break
        v = f"{date_part} {time_part}"

    # 只有日期则补齐时间
    if len(v) == 10:
        v = v + (" 23:59:59" if is_end else " 00:00:00")

    # 只有到分钟的时间则补秒
    if len(v) == 16:
        v = v + ":00"

    return v

def normalize_request(payload: Dict[str, Any]) -> Dict[str, Any]:
    report_type = payload.get('report_type', 'stat')
    dims = payload.get('dimensions') or payload.get('compare_dimensions') or payload.get('dims') or []

    start_date = _normalize_datetime(payload.get("start_date"), is_end=False)
    end_date = _normalize_datetime(payload.get("end_date"), is_end=True)

    normalized = {
        "reportType": "statistical" if report_type == "stat" else "trend",
        "reportStyle": payload.get("report_style"),
        "dimensions": dims,
        "metric": payload.get("metric", "sales_amount"),
        "granularity": payload.get("granularity", "month"),
        "since": start_date,
        "until": end_date,
        "topN": int(payload.get("top_n", 10) or 10),
        "filters": {}
    }
    return normalized