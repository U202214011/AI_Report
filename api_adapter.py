from typing import Dict, Any, List


def _normalize_datetime(value: Any, is_end: bool) -> Any:
    """
    统一时间输入：
    - 支持 YYYY-MM-DD / YYYY-MM-DDTHH:MM / YYYY-MM-DDTHH:MM:SS / 带Z/时区
    - 仅日期时补齐到 00:00:00 或 23:59:59
    - 仅到分钟时补秒
    """
    if not value:
        return None

    v = str(value).strip()
    if not v:
        return None

    # 统一 T / Z
    v = v.replace("T", " ")
    if v.endswith("Z"):
        v = v[:-1]

    # 去掉时区偏移（如 +08:00 / -05:00）
    if " " in v:
        date_part, time_part = v.split(" ", 1)
        for sep in ["+", "-"]:
            if sep in time_part[1:]:
                time_part = time_part.split(sep)[0]
                break
        v = f"{date_part} {time_part}"

    # 只有日期，补齐时间
    if len(v) == 10:
        v = v + (" 23:59:59" if is_end else " 00:00:00")

    # 只有到分钟，补秒
    if len(v) == 16:
        v = v + ":00"

    return v


# 报告风格归一化
_STYLE_NORMALIZE = {
    "simple": "simple",
    "attribution": "attribution",
    "forecast": "forecast",
    "standard": "standard",
    "简明分析性": "simple",
    "归因解析型": "attribution",
    "预测建议型": "forecast",
    "综合标准型": "standard",
}

# 维度归一化（中英文都支持）
_DIM_NORMALIZE = {
    "total": "total", "总量": "total",
    "genre": "genre", "流派": "genre", "音乐流派": "genre",
    "artist": "artist", "艺术家": "artist",
    "country": "country", "国家": "country",
    "city": "city", "城市": "city",
    "customer": "customer", "客户": "customer",
    "employee": "employee", "员工": "employee",
}


def _normalize_dims(dims_raw: Any) -> List[str]:
    out: List[str] = []
    for d in (dims_raw or []):
        key = str(d).strip()
        v = _DIM_NORMALIZE.get(key)
        if v and v not in out:
            out.append(v)
    return out


def normalize_request(payload: Dict[str, Any]) -> Dict[str, Any]:
    # report type
    report_type_raw = payload.get("report_type", "stat")
    report_type = str(report_type_raw).strip().lower()
    # 兼容中文输入
    if report_type in ("统计型", "统计", "statistical"):
        report_type = "stat"
    elif report_type in ("趋势型", "趋势"):
        report_type = "trend"

    # dimensions
    dims_raw = (
        payload.get("dimensions")
        or payload.get("compare_dimensions")
        or payload.get("dims")
        or []
    )
    dims = _normalize_dims(dims_raw)

    # style
    style_raw = payload.get("report_style") or payload.get("reportStyle") or payload.get("style")
    style_norm = None
    if style_raw is not None:
        s = str(style_raw).strip()
        style_norm = _STYLE_NORMALIZE.get(s, s if s else None)

    # datetime
    start_date = _normalize_datetime(payload.get("start_date"), is_end=False)
    end_date = _normalize_datetime(payload.get("end_date"), is_end=True)

    # metric / granularity
    metric = str(payload.get("metric", "sales_amount")).strip() or "sales_amount"
    granularity = str(payload.get("granularity", "month")).strip() or "month"

    # topN 安全转换
    try:
        top_n = int(payload.get("top_n", 10) or 10)
    except Exception:
        top_n = 10
    if top_n < 1:
        top_n = 1
    if top_n > 200:
        top_n = 200

    normalized = {
        "reportType": "statistical" if report_type == "stat" else "trend",
        "reportStyle": style_norm,
        "dimensions": dims,
        "metric": metric,
        "granularity": granularity,
        "since": start_date,
        "until": end_date,
        "topN": top_n,
        "filters": {}
    }
    return normalized