from typing import Dict, Any, List, Optional
import json
import os
import re
import numpy as np
from decimal import Decimal
from datetime import datetime
from dateutil.relativedelta import relativedelta
from report_service import (
    build_period_trend,
    build_dimension_trend,
    run_query,
    run_aggregation,
    build_period_range,
    build_total_series,
    build_series_by_dimension,
    select_top_categories
)

REPORT_TYPE_MAP = {
    "stat": "statistical",
    "statistical": "statistical",
    "统计型": "statistical",
    "统计": "statistical",
    "trend": "trend",
    "趋势型": "trend",
    "趋势": "trend"
}

METRIC_MAP = {
    "sales_amount": "sales_amount",
    "销售额": "sales_amount",
    "order_count": "order_count",
    "订单量": "order_count",
    "订单数": "order_count",
    "avg_order_value": "avg_order_value",
    "客单价": "avg_order_value"
}

GRANULARITY_MAP = {
    "month": "month",
    "月": "month",
    "quarter": "quarter",
    "季": "quarter",
    "季度": "quarter",
    "year": "year",
    "年": "year"
}

DIMENSION_MAP = {
    "total": "total",
    "总量": "total",
    "genre": "genre",
    "音乐流派": "genre",
    "artist": "artist",
    "艺术家": "artist",
    "country": "country",
    "国家": "country",
    "city": "city",
    "城市": "city",
    "customer": "customer",
    "客户": "customer",
    "employee": "employee",
    "员工": "employee"
}

METRIC_LABELS_CN = {
    "sales_amount": "销售额",
    "order_count": "订单数",
    "avg_order_value": "客单价"
}

GRANULARITY_LABELS_CN = {
    "month": "月",
    "quarter": "季度",
    "year": "年"
}

DIMENSION_LABELS_CN = {
    "total": "总量",
    "genre": "流派",
    "artist": "艺术家",
    "country": "国家",
    "city": "城市",
    "customer": "客户",
    "employee": "员工"
}

CHART_MEMORY: Dict[str, str] = {}

TEMPLATE_FILE = os.path.join(os.path.dirname(__file__), "prompt_templates.json")

_PERIOD_YEAR_RE = re.compile(r"^(\d{4})$")
_PERIOD_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
_PERIOD_DAY_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_PERIOD_QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$")

def load_templates() -> Dict[str, Any]:
    try:
        with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def pick_template(report_type: str, templates: Dict[str, Any]) -> str:
    env_key = os.getenv("PROMPT_TEMPLATE")
    if env_key:
        env_key = env_key.strip()
        if env_key in templates:
            return templates[env_key].get("template", "")

    if report_type in templates:
        return templates[report_type].get("template", "")
    if "default" in templates:
        return templates["default"].get("template", "")
    return ""

class _SafeFormatDict(dict):
    def __missing__(self, key):
        return "N/A"

def render_template(template_text: str, payload: Dict[str, Any]) -> str:
    try:
        return template_text.format_map(_SafeFormatDict(payload))
    except Exception:
        return template_text

def _json_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    return str(obj)

def cache_chart(key: Optional[str], image: Optional[str]) -> None:
    if not key or not image:
        return
    CHART_MEMORY[key] = image

def get_cached_chart(key: str) -> Optional[str]:
    return CHART_MEMORY.get(key)

def get_frontend_schema() -> Dict[str, Any]:
    return {
        "report_type": ["统计型", "趋势型"],
        "metric": ["销售额", "订单量", "客单价"],
        "granularity": ["月", "季", "年"],
        "top_n": "int",
        "start_date": "YYYY-MM-DD",
        "end_date": "YYYY-MM-DD",
        "dimensions": ["总量", "流派", "艺术家", "国家", "城市", "客户", "员工"]
    }

def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0

def _sum_values(rows: List[Dict[str, Any]]) -> float:
    return sum(_safe_float(r.get("value")) for r in rows)

def _compute_total_metric(metric: str, granularity: str, since: Optional[str], until: Optional[str]) -> float:
    if metric != "avg_order_value":
        sql, params = build_period_trend(metric, granularity, since, until)
        rows = run_query(sql, params)
        return _sum_values(rows)

    sales_sql, sales_params = build_period_trend("sales_amount", granularity, since, until)
    order_sql, order_params = build_period_trend("order_count", granularity, since, until)
    sales_rows = run_query(sales_sql, sales_params)
    order_rows = run_query(order_sql, order_params)
    total_sales = _sum_values(sales_rows)
    total_orders = _sum_values(order_rows)
    return total_sales / total_orders if total_orders else 0.0

def _compute_growth(series: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    growth = []
    prev_value = None
    for item in series:
        value = _safe_float(item.get("y"))
        change = value - prev_value if prev_value is not None else None
        pct = (change / prev_value * 100) if prev_value not in (None, 0) else None
        growth.append({
            "period": item.get("x"),
            "value": value,
            "prev_value": prev_value,
            "change": change,
            "change_pct": pct
        })
        prev_value = value
    return growth

def _trend_direction(values: List[float]) -> str:
    if len(values) < 2:
        return "稳定"
    x = np.arange(len(values))
    slope = np.polyfit(x, values, 1)[0]
    avg = np.mean(values) if values else 0
    threshold = max(abs(avg) * 0.01, 1e-6)
    if abs(slope) <= threshold:
        return "稳定"
    return "上升" if slope > 0 else "下降"

def _extract_peak_valley(series: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not series:
        return {"peak": None, "valley": None}
    values = [(item.get("x"), _safe_float(item.get("y"))) for item in series]
    peak = max(values, key=lambda x: x[1])
    valley = min(values, key=lambda x: x[1])
    return {
        "peak": {"period": peak[0], "value": peak[1]},
        "valley": {"period": valley[0], "value": valley[1]}
    }

def _parse_period_label(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    v = str(value).strip()
    if not v:
        return None

    m = _PERIOD_QUARTER_RE.match(v)
    if m:
        year = int(m.group(1))
        q = int(m.group(2))
        month = (q - 1) * 3 + 1
        return datetime(year, month, 1)

    m = _PERIOD_DAY_RE.match(v)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    m = _PERIOD_MONTH_RE.match(v)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), 1)

    m = _PERIOD_YEAR_RE.match(v)
    if m:
        return datetime(int(m.group(1)), 1, 1)

    return None

def _format_period_label(granularity: str, dt: datetime) -> str:
    if granularity == "quarter":
        q = (dt.month - 1) // 3 + 1
        return f"{dt.year}-Q{q}"
    if granularity == "month":
        return dt.strftime("%Y-%m")
    if granularity == "year":
        return dt.strftime("%Y")
    return dt.strftime("%Y-%m-%d")

def _shift_period_label(granularity: str, label: Any, steps: int) -> Optional[str]:
    dt = _parse_period_label(label)
    if not dt:
        return None
    if granularity == "month":
        dt = dt + relativedelta(months=steps)
    elif granularity == "quarter":
        dt = dt + relativedelta(months=steps * 3)
    elif granularity == "year":
        dt = dt + relativedelta(years=steps)
    elif granularity == "week":
        dt = dt + relativedelta(weeks=steps)
    else:
        dt = dt + relativedelta(days=steps)
    return _format_period_label(granularity, dt)

def _compute_volatility(values: List[float]) -> Dict[str, float]:
    if not values:
        return {"mean": 0.0, "std": 0.0, "coef_var": 0.0}
    mean = float(np.mean(values))
    std = float(np.std(values))
    coef = std / mean if mean not in (0, None) else 0.0
    return {"mean": mean, "std": std, "coef_var": coef}

def _compute_basic_stats(values: List[float]) -> Dict[str, float]:
    if not values:
        return {
            "sum": 0.0, "mean": 0.0, "max": 0.0, "min": 0.0,
            "median": 0.0, "std": 0.0, "count": 0
        }
    return {
        "sum": float(np.sum(values)),
        "mean": float(np.mean(values)),
        "max": float(np.max(values)),
        "min": float(np.min(values)),
        "median": float(np.median(values)),
        "std": float(np.std(values)),
        "count": len(values)
    }

def _max_growth_period(series: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if len(series) < 2:
        return None
    max_change = None
    max_record = None
    for i in range(1, len(series)):
        prev = series[i - 1]
        curr = series[i]
        prev_val = _safe_float(prev.get("y"))
        curr_val = _safe_float(curr.get("y"))
        change = curr_val - prev_val
        if max_change is None or change > max_change:
            pct = (change / prev_val * 100) if prev_val not in (0, None) else None
            max_change = change
            max_record = {
                "fromPeriod": prev.get("x"),
                "toPeriod": curr.get("x"),
                "prevValue": prev_val,
                "currentValue": curr_val,
                "change": change,
                "changePct": pct
            }
    return max_record

def _min_growth_period(series: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if len(series) < 2:
        return None
    min_change = None
    min_record = None
    for i in range(1, len(series)):
        prev = series[i - 1]
        curr = series[i]
        prev_val = _safe_float(prev.get("y"))
        curr_val = _safe_float(curr.get("y"))
        change = curr_val - prev_val
        if min_change is None or change < min_change:
            pct = (change / prev_val * 100) if prev_val not in (0, None) else None
            min_change = change
            min_record = {
                "fromPeriod": prev.get("x"),
                "toPeriod": curr.get("x"),
                "prevValue": prev_val,
                "currentValue": curr_val,
                "change": change,
                "changePct": pct
            }
    return min_record

def _period_of_value(series: List[Dict[str, Any]], target_value: float) -> Optional[str]:
    if not series:
        return None
    closest = min(series, key=lambda x: abs(_safe_float(x.get("y")) - target_value))
    return closest.get("x")

def _compute_dim_totals(rows: List[Dict[str, Any]], dim_key: str) -> Dict[str, Any]:
    totals: Dict[str, float] = {}
    for r in rows:
        label = r.get(dim_key)
        totals[label] = totals.get(label, 0.0) + _safe_float(r.get("value"))
    total_all = sum(totals.values())
    return {"totals": totals, "total_all": total_all}

def _build_stat_dimension_summary(
    dim: str,
    metric: str,
    since: Optional[str],
    until: Optional[str],
    top_n: int
) -> Dict[str, Any]:
    payload = {
        "reportType": "statistical",
        "dimensions": [dim],
        "metric": metric,
        "since": since,
        "until": until,
        "topN": None,
        "filters": {}
    }
    rows = run_aggregation(payload)
    total_value = _sum_values(rows)
    top_categories = select_top_categories(rows, dim, top_n)
    top_rows = [r for r in rows if r.get(dim) in top_categories]
    other_value = _sum_values([r for r in rows if r.get(dim) not in top_categories])
    if other_value > 0:
        top_rows.append({dim: "其他", "value": other_value})
        top_categories = top_categories + ["其他"]

    ranking = [
        {
            "name": r.get(dim),
            "value": _safe_float(r.get("value")),
            "share_pct": (_safe_float(r.get("value")) / total_value * 100) if total_value else 0
        }
        for r in top_rows
    ]

    values = [item["value"] for item in ranking]
    max_value = max(values) if values else 0
    min_value = min(values) if values else 0
    max_name = next((i["name"] for i in ranking if i["value"] == max_value), None)
    min_name = next((i["name"] for i in ranking if i["value"] == min_value), None)

    return {
        "dimension": dim,
        "dimensionLabel": DIMENSION_LABELS_CN.get(dim, dim),
        "total": total_value,
        "topCategories": top_categories,
        "ranking": ranking,
        "topSharePct": sum(item["share_pct"] for item in ranking),
        "maxValue": max_value,
        "maxName": max_name,
        "minValue": min_value,
        "minName": min_name
    }

def _build_dim_table_texts(dimension_summaries: List[Dict[str, Any]]) -> str:
    if not dimension_summaries:
        return "（无维度明细数据）"
    blocks = []
    for dim_summary in dimension_summaries:
        label = dim_summary.get("dimensionLabel") or "维度"
        ranking = dim_summary.get("ranking") or dim_summary.get("topN") or []
        if not ranking:
            blocks.append(f"{label}：\n（无维度明细数据）")
            continue
        lines = [f"{label}："]
        for idx, item in enumerate(ranking, 1):
            name = item.get("name")
            value = _safe_float(item.get("value"))
            pct = item.get("share_pct", 0)
            lines.append(f"{idx}. {name}：{value:.2f}（占比{pct:.2f}%）")
        lines.append(
            f"最大值：{dim_summary.get('maxName')}（{dim_summary.get('maxValue', 0):.2f}）"
        )
        lines.append(
            f"最小值：{dim_summary.get('minName')}（{dim_summary.get('minValue', 0):.2f}）"
        )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)

def _build_trend_dim_table_texts(dimension_summaries: List[Dict[str, Any]]) -> str:
    if not dimension_summaries:
        return "（无维度明细数据）"
    blocks = []
    for dim_summary in dimension_summaries:
        label = dim_summary.get("dimensionLabel") or "维度"
        categories = dim_summary.get("categories") or []
        if not categories:
            blocks.append(f"{label}：\n（无维度明细数据）")
            continue
        header = (
            f"{label}（Top{dim_summary.get('topN', 'N')}）占比{dim_summary.get('topSharePct', 0):.2f}%，"
            f"Top3 {dim_summary.get('top3SharePct', 0):.2f}%，Top5 {dim_summary.get('top5SharePct', 0):.2f}%"
        )
        lines = [header]
        for idx, cat in enumerate(categories, 1):
            name = cat.get("name")
            trend = cat.get("trendDirection", "N/A")
            vol = cat.get("volatility", {}) or {}
            std = vol.get("std", 0)
            coef = vol.get("coef_var", 0)
            max_growth = cat.get("maxGrowthPeriod") or {}
            min_growth = cat.get("minGrowthPeriod") or {}
            peak = cat.get("peakValley", {}).get("peak")
            valley = cat.get("peakValley", {}).get("valley")
            share = cat.get("sharePct")
            contrib = cat.get("growthContributionPct")

            lines.append(
                f"{idx}. {name}：占比{share:.2f}%；趋势{trend}；波动标准差{std:.2f}，变异系数{coef:.2f}"
            )
            lines.append(
                f"   - 增长贡献率：{contrib:.2f}%"
            )
            if max_growth:
                lines.append(
                    f"   - 最大环比：{max_growth.get('fromPeriod')}→{max_growth.get('toPeriod')}（+{max_growth.get('change', 0):.2f}）"
                )
            if min_growth:
                lines.append(
                    f"   - 最小环比：{min_growth.get('fromPeriod')}→{min_growth.get('toPeriod')}（{min_growth.get('change', 0):.2f}）"
                )
            if peak and valley:
                lines.append(
                    f"   - 峰值：{peak.get('period')}（{peak.get('value'):.2f}）；谷值：{valley.get('period')}（{valley.get('value'):.2f}）"
                )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)

def _build_stat_llm_summary(
    metric: str,
    metric_label: str,
    granularity: str,
    gran_label: str,
    since: Optional[str],
    until: Optional[str],
    top_n: int,
    dims: List[str],
    total_metric: float,
    dimension_summaries: List[Dict[str, Any]],
    total_series: List[Dict[str, Any]]
) -> Dict[str, Any]:
    values = [_safe_float(item.get("y")) for item in total_series]
    basic_stats = _compute_basic_stats(values)
    max_period = _period_of_value(total_series, basic_stats.get("max", 0))
    min_period = _period_of_value(total_series, basic_stats.get("min", 0))
    median_period = _period_of_value(total_series, basic_stats.get("median", 0))

    dim_summaries = []
    for d in dimension_summaries:
        ranking = d.get("ranking") or []
        top3_share = sum(item.get("share_pct", 0) for item in ranking[:3])
        top5_share = sum(item.get("share_pct", 0) for item in ranking[:5])
        dim_summaries.append({
            "dimension": d.get("dimension"),
            "dimensionLabel": d.get("dimensionLabel"),
            "total": d.get("total"),
            "topN": ranking,
            "top3SharePct": top3_share,
            "top5SharePct": top5_share,
            "topSharePct": d.get("topSharePct"),
            "maxValue": d.get("maxValue"),
            "maxName": d.get("maxName"),
            "minValue": d.get("minValue"),
            "minName": d.get("minName")
        })

    overview_sentence = (
        f"{metric_label}统计范围：{since or 'N/A'} ~ {until or 'N/A'}，"
        f"总量为{total_metric:.2f}，时间粒度为{gran_label}。"
    )

    return {
        "metric": metric,
        "metricLabel": metric_label,
        "granularity": granularity,
        "granularityLabel": gran_label,
        "since": since,
        "until": until,
        "topN": top_n,
        "dimensions": dims,
        "total": total_metric,
        "series": total_series,
        "basicStats": basic_stats,
        "maxPeriod": max_period,
        "minPeriod": min_period,
        "medianPeriod": median_period,
        "dimensionsSummary": dim_summaries,
        "natural_fragments": {
            "overview_sentence": overview_sentence
        }
    }

def _build_trend_llm_summary(
    metric: str,
    metric_label: str,
    granularity: str,
    gran_label: str,
    since: Optional[str],
    until: Optional[str],
    top_n: int,
    dims: List[str],
    series: List[Dict[str, Any]],
    trend_direction: str,
    dimension_series: List[Dict[str, Any]]
) -> Dict[str, Any]:
    values = [_safe_float(item.get("y")) for item in series]
    basic_stats = _compute_basic_stats(values)
    max_period = _period_of_value(series, basic_stats.get("max", 0))
    min_period = _period_of_value(series, basic_stats.get("min", 0))
    median_period = _period_of_value(series, basic_stats.get("median", 0))

    total_growth = (_safe_float(series[-1].get("y")) - _safe_float(series[0].get("y"))) if series else 0.0

    dim_summaries = []
    for dim_block in dimension_series:
        dim = dim_block.get("dimension")
        dim_label = dim_block.get("dimensionLabel")
        totals_map = dim_block.get("categoryTotals") or {}
        total_all = dim_block.get("totalAll") or 0.0

        sorted_totals = sorted(totals_map.items(), key=lambda x: x[1], reverse=True)
        top3_share = sum(v for _, v in sorted_totals[:3]) / total_all * 100 if total_all else 0.0
        top5_share = sum(v for _, v in sorted_totals[:5]) / total_all * 100 if total_all else 0.0
        topN_share = sum(v for _, v in sorted_totals[:top_n]) / total_all * 100 if total_all else 0.0

        # 先收集每个类别的增长值，用于计算“绝对贡献率”
        cat_growths = []
        for s in dim_block.get("series", []):
            data = s.get("data") or []
            cat_growth = (_safe_float(data[-1].get("y")) - _safe_float(data[0].get("y"))) if data else 0.0
            cat_growths.append(cat_growth)

        total_abs_growth = sum(abs(g) for g in cat_growths)

        categories = []
        for idx, s in enumerate(dim_block.get("series", [])):
            label = s.get("label")
            data = s.get("data") or []
            v = [_safe_float(p.get("y")) for p in data]
            max_growth_cat = _max_growth_period(data)
            min_growth_cat = _min_growth_period(data)
            peak_valley_cat = _extract_peak_valley(data)
            share_pct = (totals_map.get(label, 0.0) / total_all * 100) if total_all else 0.0
            cat_growth = cat_growths[idx] if idx < len(cat_growths) else 0.0

            # ✅ 修复点：改为“绝对增长贡献率”
            growth_contrib = abs(cat_growth) / total_abs_growth * 100 if total_abs_growth else 0.0

            categories.append({
                "name": label,
                "series": data,
                "trendDirection": _trend_direction(v),
                "volatility": _compute_volatility(v),
                "maxGrowthPeriod": max_growth_cat,
                "minGrowthPeriod": min_growth_cat,
                "peakValley": peak_valley_cat,
                "sharePct": share_pct,
                "growthContributionPct": growth_contrib
            })

        dim_summaries.append({
            "dimension": dim,
            "dimensionLabel": dim_label,
            "topCategories": dim_block.get("topCategories") or [],
            "categories": categories,
            "topSharePct": topN_share,
            "top3SharePct": top3_share,
            "top5SharePct": top5_share,
            "topN": top_n
        })

    overview_sentence = (
        f"{metric_label}趋势范围：{since or 'N/A'} ~ {until or 'N/A'}，"
        f"时间粒度为{gran_label}，整体趋势{trend_direction}。"
    )

    return {
        "metric": metric,
        "metricLabel": metric_label,
        "granularity": granularity,
        "granularityLabel": gran_label,
        "since": since,
        "until": until,
        "topN": top_n,
        "dimensions": dims,
        "series": series,
        "trendDirection": trend_direction,
        "basicStats": basic_stats,
        "maxPeriod": max_period,
        "minPeriod": min_period,
        "medianPeriod": median_period,
        "dimensionsSummary": dim_summaries,
        "natural_fragments": {
            "overview_sentence": overview_sentence
        }
    }

def _format_metric_value(metric: str, value: float) -> str:
    if metric == "order_count":
        return f"{value:,.0f} 笔"
    if metric == "avg_order_value":
        return f"{value:,.2f} 元/笔"
    return f"{value:,.2f} 元"

def _build_total_series_text(series: List[Dict[str, Any]], metric: str) -> str:
    if not series:
        return "（无时间序列数据）"
    lines = []
    for item in series:
        label = item.get("x")
        value = _safe_float(item.get("y"))
        lines.append(f"{label}: {_format_metric_value(metric, value)}")
    return "\n".join(lines)

def build_prompt_bundle(normalized: Dict[str, Any], plots: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    report_type = normalized.get("reportType", "statistical")
    metric = normalized.get("metric", "sales_amount")
    granularity = normalized.get("granularity", "month")
    top_n = int(normalized.get("topN") or 10)
    since = normalized.get("since")
    until = normalized.get("until")
    dims = normalized.get("dimensions") or ["total"]
    dims = [d for d in dims if d in DIMENSION_LABELS_CN]
    if not dims:
        dims = ["total"]

    metric_label = METRIC_LABELS_CN.get(metric, metric)
    gran_label = GRANULARITY_LABELS_CN.get(granularity, granularity)
    periods = build_period_range(granularity, since, until)

    chart_keys = []
    if plots:
        for idx, plot in enumerate(plots):
            key = plot.get("title") or f"chart_{idx + 1}"
            chart_keys.append(key)

    summary = {
        "reportType": report_type,
        "metric": metric,
        "metricLabel": metric_label,
        "granularity": granularity,
        "granularityLabel": gran_label,
        "topN": top_n,
        "since": since,
        "until": until,
        "dimensions": dims
    }

    prompt_data: Dict[str, Any] = {
        "summary": summary,
        "periods": periods,
        "charts": {
            "count": len(chart_keys),
            "keys": chart_keys
        },
        "statistical": {},
        "trend": {},
        "llmSummary": {}
    }

    if report_type == "statistical":
        total_metric = _compute_total_metric(metric, granularity, since, until)
        dimension_summaries = [
            _build_stat_dimension_summary(dim, metric, since, until, top_n)
            for dim in dims if dim != "total"
        ]

        sql, params = build_period_trend(metric, granularity, since, until)
        rows = run_query(sql, params)
        total_series = build_total_series(rows, granularity, periods=periods if periods else None)

        prompt_data["statistical"] = {
            "total": total_metric,
            "dimensions": dimension_summaries
        }
        prompt_data["llmSummary"]["statistical"] = _build_stat_llm_summary(
            metric=metric,
            metric_label=metric_label,
            granularity=granularity,
            gran_label=gran_label,
            since=since,
            until=until,
            top_n=top_n,
            dims=dims,
            total_metric=total_metric,
            dimension_summaries=dimension_summaries,
            total_series=total_series
        )
    else:
        sql, params = build_period_trend(metric, granularity, since, until)
        rows = run_query(sql, params)
        series = build_total_series(rows, granularity, periods=periods if periods else None)

        dimension_series = []
        for dim in [d for d in dims if d != "total"]:
            sql, params = build_dimension_trend(metric, granularity, dim, since, until)
            dim_rows = run_query(sql, params)
            totals_info = _compute_dim_totals(dim_rows, dim)
            top_categories = select_top_categories(dim_rows, dim, top_n)
            if top_categories:
                dim_rows = [r for r in dim_rows if r.get(dim) in top_categories]
            series_by_dim = build_series_by_dimension(dim_rows, dim, granularity, periods=periods if periods else None)
            dimension_series.append({
                "dimension": dim,
                "dimensionLabel": DIMENSION_LABELS_CN.get(dim, dim),
                "topCategories": top_categories,
                "series": series_by_dim,
                "categoryTotals": totals_info.get("totals"),
                "totalAll": totals_info.get("total_all")
            })

        prompt_data["trend"] = {
            "series": series,
            "trendDirection": _trend_direction([_safe_float(i.get("y")) for i in series]),
            "dimensions": dimension_series
        }
        prompt_data["llmSummary"]["trend"] = _build_trend_llm_summary(
            metric=metric,
            metric_label=metric_label,
            granularity=granularity,
            gran_label=gran_label,
            since=since,
            until=until,
            top_n=top_n,
            dims=dims,
            series=series,
            trend_direction=_trend_direction([_safe_float(i.get("y")) for i in series]),
            dimension_series=dimension_series
        )

    role_context = {
        "analyst_level": "资深数据分析师",
        "domain": "销售数据",
        "decision_type": "经营决策",
        "report_audience": "管理层"
    }

    llm_data = prompt_data["llmSummary"]["statistical"] if report_type == "statistical" else prompt_data["llmSummary"]["trend"]
    basic_stats = llm_data.get("basicStats", {})

    max_period = llm_data.get("maxPeriod")
    min_period = llm_data.get("minPeriod")
    median_period = llm_data.get("medianPeriod")

    total_sales = _compute_total_metric("sales_amount", granularity, since, until)
    total_orders = _compute_total_metric("order_count", granularity, since, until)
    avg_order = total_sales / total_orders if total_orders else 0.0

    if metric == "sales_amount":
        total_value_text = f"{total_sales:,.2f} 元"
    elif metric == "order_count":
        total_value_text = f"{total_orders:,.0f} 笔"
    else:
        total_value_text = f"{avg_order:,.2f} 元/笔"

    key_metrics = {
        "total_value_text": total_value_text,
        "transaction_count": f"{total_orders:,.0f}",
        "avg_order_value_text": f"{avg_order:,.2f} 元",
        "period_mean_text": f"{basic_stats.get('mean', 0.0):,.2f}",
        "period_max_text": f"{basic_stats.get('max', 0.0):,.2f}",
        "period_max_period": max_period or "N/A",
        "period_min_text": f"{basic_stats.get('min', 0.0):,.2f}",
        "period_min_period": min_period or "N/A",
        "period_median_text": f"{basic_stats.get('median', 0.0):,.2f}",
        "period_median_period": median_period or "N/A"
    }

    if report_type == "statistical":
        task_definition = {
            "analysis_type": "统计型",
            "focus": f"{metric_label}结构与Top{top_n}贡献",
            "depth": "结构、占比、集中度与对比"
        }
        dim_summaries = llm_data.get("dimensionsSummary") or []
        dim_labels = [d.get("dimensionLabel") for d in dim_summaries if d.get("dimensionLabel")]
        dim_label = "、".join(dim_labels) if dim_labels else "维度"
        dim_table = _build_dim_table_texts(dim_summaries)
    else:
        task_definition = {
            "analysis_type": "趋势型",
            "focus": f"{metric_label}趋势变化与波动诊断",
            "depth": "趋势方向、波动、异常与结构差异"
        }
        dim_summaries = llm_data.get("dimensionsSummary") or []
        dim_labels = [d.get("dimensionLabel") for d in dim_summaries if d.get("dimensionLabel")]
        dim_label = "、".join(dim_labels) if dim_labels else "维度"
        dim_table = _build_trend_dim_table_texts(dim_summaries)

    format_requirements = {
        "sections": "概览/关键发现/原因分析/建议",
        "tone": "专业、详细、可执行",
        "number_format": "金额保留2位小数，比例保留2位小数",
        "length_limit": "600-1000字"
    }

    constraints_yaml = "\n".join([
        "- 仅使用给定数据",
        "- 不得编造结论",
        "- 如数据不足需说明"
    ])

    limitations_note = "若部分维度/时间粒度无数据，请在报告中说明限制。"

    total_series_text = _build_total_series_text(llm_data.get("series") or [], metric)

    template_payload = {
        "role_context": role_context,
        "task_definition": task_definition,
        "data_summary": llm_data,
        "key_metrics": key_metrics,
        "dimension_analysis": {
            "dim_label": dim_label
        },
        "dim_table": dim_table,
        "limitations_note": limitations_note,
        "format_requirements": format_requirements,
        "constraints_yaml": constraints_yaml,
        "series_granularity_label": gran_label,
        "total_series_text": total_series_text
    }

    templates = load_templates()
    template_text = pick_template(report_type, templates)
    prompt_text = render_template(template_text, template_payload)

    return {
        "prompt": prompt_text,
        "promptData": prompt_data,
        "frontendSchema": get_frontend_schema()
    }