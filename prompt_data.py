from typing import Dict, Any, List, Optional, Tuple
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

REPORT_STYLE_MAP = {
    "简明分析性": "simple",
    "归因解析型": "attribution",
    "预测建议型": "forecast",
    "综合标准型": "standard",
    "simple": "simple",
    "attribution": "attribution",
    "forecast": "forecast",
    "standard": "standard"
}

STYLE_APPENDIX = {
    # 降级为“补充提醒”，主控制放入模板主体
    "statistical.simple": "【补充提醒】简明分析性：先结论，少铺陈，3-5条要点优先。",
    "statistical.attribution": "【补充提醒】归因解析型：区分主因/次因，无法验证因果需标注“推测”。",
    "statistical.forecast": "【补充提醒】预测建议型：给短中期方向、风险触发条件和优先级建议。",
    "statistical.standard": "【补充提醒】综合标准型：保持概览/发现/原因/建议完整平衡。",
    "trend.simple": "【补充提醒】简明分析性：先给趋势结论，再列关键拐点。",
    "trend.attribution": "【补充提醒】归因解析型：强调维度对趋势变化的贡献。",
    "trend.forecast": "【补充提醒】预测建议型：给趋势判断、风险触发与可执行动作。",
    "trend.standard": "【补充提醒】综合标准型：覆盖趋势、波动、维度差异与建议。"
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
_UNRESOLVED_PLACEHOLDER_RE = re.compile(r"\{[^{}]+\}")

_TEMPLATE_DEBUG_STATE: Dict[str, Any] = {
    "template_file": TEMPLATE_FILE,
    "template_file_exists": False,
    "loaded": False,
    "error": None,
    "keys": [],
    "env_prompt_template": None,
    "selected_key": None,
    "selected_by": None,
    "selected_template_len": 0,
    "used_fallback_default": False,
    "rendered_prompt_len": 0,
    "render_ok": False,
    "render_error": None,
    "unresolved_placeholder_count": 0,
    "fallback_reason": None,
    "style_key": None,
    "style_appendix_len": 0
}


def _reset_template_debug_state() -> None:
    _TEMPLATE_DEBUG_STATE.update({
        "template_file": TEMPLATE_FILE,
        "template_file_exists": os.path.exists(TEMPLATE_FILE),
        "loaded": False,
        "error": None,
        "keys": [],
        "env_prompt_template": os.getenv("PROMPT_TEMPLATE"),
        "selected_key": None,
        "selected_by": None,
        "selected_template_len": 0,
        "used_fallback_default": False,
        "rendered_prompt_len": 0,
        "render_ok": False,
        "render_error": None,
        "unresolved_placeholder_count": 0,
        "fallback_reason": None,
        "style_key": None,
        "style_appendix_len": 0
    })


def get_template_debug_state() -> Dict[str, Any]:
    return dict(_TEMPLATE_DEBUG_STATE)


def load_templates() -> Dict[str, Any]:
    _reset_template_debug_state()
    try:
        with open(TEMPLATE_FILE, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            _TEMPLATE_DEBUG_STATE["error"] = "template JSON root is not an object"
            return {}
        _TEMPLATE_DEBUG_STATE["loaded"] = True
        _TEMPLATE_DEBUG_STATE["keys"] = list(data.keys())
        return data
    except Exception as e:
        _TEMPLATE_DEBUG_STATE["error"] = repr(e)
        return {}


def pick_template(key: str, templates: Dict[str, Any]) -> str:
    env_key = os.getenv("PROMPT_TEMPLATE")
    if env_key:
        env_key = env_key.strip()
        cfg = templates.get(env_key)
        if isinstance(cfg, dict):
            t = cfg.get("template") or ""
            t = t if isinstance(t, str) else str(t)
            _TEMPLATE_DEBUG_STATE["selected_key"] = env_key
            _TEMPLATE_DEBUG_STATE["selected_by"] = "env"
            _TEMPLATE_DEBUG_STATE["selected_template_len"] = len(t)
            return t

    cfg = templates.get(key)
    if isinstance(cfg, dict):
        t = cfg.get("template") or ""
        t = t if isinstance(t, str) else str(t)
        _TEMPLATE_DEBUG_STATE["selected_key"] = key
        _TEMPLATE_DEBUG_STATE["selected_by"] = "report_type"
        _TEMPLATE_DEBUG_STATE["selected_template_len"] = len(t)
        return t

    cfg = templates.get("default")
    if isinstance(cfg, dict):
        t = cfg.get("template") or ""
        t = t if isinstance(t, str) else str(t)
        _TEMPLATE_DEBUG_STATE["selected_key"] = "default"
        _TEMPLATE_DEBUG_STATE["selected_by"] = "default"
        _TEMPLATE_DEBUG_STATE["selected_template_len"] = len(t)
        return t

    _TEMPLATE_DEBUG_STATE["selected_key"] = None
    _TEMPLATE_DEBUG_STATE["selected_by"] = "none"
    _TEMPLATE_DEBUG_STATE["selected_template_len"] = 0
    return ""


class _SafeFormatDict(dict):
    def __missing__(self, key):
        return "N/A"


def _count_unresolved_placeholders(text: str) -> int:
    return len(_UNRESOLVED_PLACEHOLDER_RE.findall(text or ""))


def _has_unresolved_placeholders(text: str) -> bool:
    return _count_unresolved_placeholders(text) > 0


def render_template(template_text: str, payload: Dict[str, Any]) -> str:
    try:
        out = template_text.format_map(_SafeFormatDict(payload))
        _TEMPLATE_DEBUG_STATE["render_ok"] = True
        _TEMPLATE_DEBUG_STATE["render_error"] = None
        return out
    except Exception as e:
        _TEMPLATE_DEBUG_STATE["render_ok"] = False
        _TEMPLATE_DEBUG_STATE["render_error"] = repr(e)
        return template_text if isinstance(template_text, str) else str(template_text)


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
        "report_style": ["简明分析性", "归因解析型", "预测建议型", "综合标准型"],
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
    sql, params = build_period_trend(metric, granularity, since, until)
    rows = run_query(sql, params)

    if metric != "avg_order_value":
        return _sum_values(rows)

    sales_sql, sales_params = build_period_trend("sales_amount", granularity, since, until)
    order_sql, order_params = build_period_trend("order_count", granularity, since, until)
    sales_rows = run_query(sales_sql, sales_params)
    order_rows = run_query(order_sql, order_params)
    total_sales = _sum_values(sales_rows)
    total_orders = _sum_values(order_rows)
    return total_sales / total_orders if total_orders else 0.0


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


def _compute_volatility(values: List[float]) -> Dict[str, float]:
    if not values:
        return {"mean": 0.0, "std": 0.0, "coef_var": 0.0}
    mean = float(np.mean(values))
    std = float(np.std(values))
    coef = std / mean if mean not in (0, None) else 0.0
    return {"mean": mean, "std": std, "coef_var": coef}


def _compute_basic_stats(values: List[float]) -> Dict[str, float]:
    if not values:
        return {"sum": 0.0, "mean": 0.0, "max": 0.0, "min": 0.0, "median": 0.0, "std": 0.0, "count": 0}
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


def _build_stat_dimension_summary(dim: str, metric: str, since: Optional[str], until: Optional[str], top_n: int) -> Dict[str, Any]:
    payload = {
        "reportType": "statistical",
        "dimensions": [dim],
        "metric": metric,
        "since": since,
        "until": until,
        "topN": None,
        "filters": {}
    }

    rows = run_aggregation(payload) or []
    if not rows:
        return {
            "dimension": dim,
            "dimensionLabel": DIMENSION_LABELS_CN.get(dim, dim),
            "total": 0.0,
            "topCategories": [],
            "ranking": [],
            "others": {"name": "其他", "value": 0.0, "share_pct": 0.0},
            "topSharePct": 0.0,
            "othersSharePct": 0.0,
            "maxValue": 0.0,
            "maxName": None,
            "minValue": 0.0,
            "minName": None
        }

    total_value = _sum_values(rows)
    top_categories = select_top_categories(rows, dim, top_n) or []
    top_rows = [r for r in rows if r.get(dim) in top_categories] if top_categories else rows[:]
    other_rows = [r for r in rows if r.get(dim) not in top_categories] if top_categories else []

    ranking = []
    for r in top_rows:
        name = r.get(dim)
        val = _safe_float(r.get("value"))
        share = (val / total_value * 100.0) if total_value else 0.0
        ranking.append({"name": name, "value": val, "share_pct": share})

    ranking.sort(key=lambda x: x["value"], reverse=True)
    top_share = sum(i["share_pct"] for i in ranking)

    other_value = sum(_safe_float(r.get("value")) for r in other_rows)
    others_share = (other_value / total_value * 100.0) if total_value else 0.0
    others_item = {"name": "其他", "value": other_value, "share_pct": others_share}

    max_item = max(ranking, key=lambda x: x["value"]) if ranking else None
    min_item = min(ranking, key=lambda x: x["value"]) if ranking else None

    return {
        "dimension": dim,
        "dimensionLabel": DIMENSION_LABELS_CN.get(dim, dim),
        "total": total_value,
        "topCategories": top_categories,
        "ranking": ranking,
        "others": others_item,
        "topSharePct": top_share,
        "othersSharePct": others_share,
        "maxValue": (max_item or {}).get("value", 0.0),
        "maxName": (max_item or {}).get("name"),
        "minValue": (min_item or {}).get("value", 0.0),
        "minName": (min_item or {}).get("name")
    }


def _build_dim_table_texts(dimension_summaries: List[Dict[str, Any]], metric: str) -> str:
    if not dimension_summaries:
        return "（无维度明细数据）"

    blocks = []
    for dim_summary in dimension_summaries:
        if not isinstance(dim_summary, dict):
            continue

        label = dim_summary.get("dimensionLabel") or "维度"
        ranking = dim_summary.get("ranking") or dim_summary.get("topN") or []
        ranking = [r for r in ranking if isinstance(r, dict) and (r.get("name") is not None)]

        if not ranking:
            blocks.append(f"{label}：\n（无维度明细数据）")
            continue

        lines = [f"{label}："]
        for idx, item in enumerate(ranking, 1):
            name = item.get("name")
            value = _safe_float(item.get("value"))
            pct = _safe_float(item.get("share_pct"))
            lines.append(f"{idx}. {name}：{_format_metric_value(metric, value)}（占比{pct:.2f}%）")

        others = dim_summary.get("others") if isinstance(dim_summary.get("others"), dict) else {}
        others_value = _safe_float(others.get("value"))
        others_pct = _safe_float(others.get("share_pct"))
        lines.append(f"其他：{_format_metric_value(metric, others_value)}（综合占比{others_pct:.2f}%）")

        lines.append(f"TopN合计占比：{_safe_float(dim_summary.get('topSharePct')):.2f}%")
        lines.append(f"其他合计占比：{_safe_float(dim_summary.get('othersSharePct')):.2f}%")
        lines.append("口径说明：以上“其他”为除TopN外所有类别的合并项，禁止重新拆分或复算。")
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks) if blocks else "（无维度明细数据）"


def _build_trend_dim_table_texts(dimension_summaries: List[Dict[str, Any]], metric: str) -> str:
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
            share = cat.get("sharePct") or 0
            growth_val = _safe_float(cat.get("growthValue"))
            contrib_signed = _safe_float(cat.get("growthContributionPctSigned"))
            contrib_abs = _safe_float(cat.get("growthContributionPctAbs"))

            lines.append(f"{idx}. {name}：占比{share:.2f}%；趋势{trend}；波动标准差{std:.2f}，变异系数{coef:.2f}")
            sign = "+" if growth_val > 0 else ""
            lines.append(f"   - 首末期变化：{sign}{_format_metric_value(metric, growth_val)}")
            lines.append(f"   - 净增长贡献率（带符号）：{contrib_signed:+.2f}%")
            lines.append(f"   - 影响贡献率（绝对值）：{contrib_abs:.2f}%")

            if max_growth:
                lines.append(
                    f"   - 最大环比：{max_growth.get('fromPeriod')}→{max_growth.get('toPeriod')}（{_format_metric_value(metric, _safe_float(max_growth.get('change', 0)))}）"
                )
            if min_growth:
                lines.append(
                    f"   - 最小环比：{min_growth.get('fromPeriod')}→{min_growth.get('toPeriod')}（{_format_metric_value(metric, _safe_float(min_growth.get('change', 0)))}）"
                )
            if peak and valley:
                lines.append(
                    f"   - 峰值：{peak.get('period')}（{_format_metric_value(metric, _safe_float(peak.get('value')))}）；"
                    f"谷值：{valley.get('period')}（{_format_metric_value(metric, _safe_float(valley.get('value')))}）"
                )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _build_stat_llm_summary(metric: str, metric_label: str, granularity: str, gran_label: str, since: Optional[str], until: Optional[str], top_n: int, dims: List[str], total_metric: float, dimension_summaries: List[Dict[str, Any]], total_series: List[Dict[str, Any]]) -> Dict[str, Any]:
    values = [_safe_float(item.get("y")) for item in total_series]
    basic_stats = _compute_basic_stats(values)
    max_period = _period_of_value(total_series, basic_stats.get("max", 0))
    min_period = _period_of_value(total_series, basic_stats.get("min", 0))
    median_period = _period_of_value(total_series, basic_stats.get("median", 0))

    dim_summaries = []
    for d in dimension_summaries:
        if not isinstance(d, dict):
            continue
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
            "others": d.get("others"),
            "othersSharePct": d.get("othersSharePct"),
            "maxValue": d.get("maxValue"),
            "maxName": d.get("maxName"),
            "minValue": d.get("minValue"),
            "minName": d.get("minName")
        })

    overview_sentence = f"{metric_label}统计范围：{since or 'N/A'} ~ {until or 'N/A'}，总量为{total_metric:.2f}，时间粒度为{gran_label}。"
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
        "natural_fragments": {"overview_sentence": overview_sentence}
    }


def _build_trend_llm_summary(metric: str, metric_label: str, granularity: str, gran_label: str, since: Optional[str], until: Optional[str], top_n: int, dims: List[str], series: List[Dict[str, Any]], trend_direction: str, dimension_series: List[Dict[str, Any]]) -> Dict[str, Any]:
    values = [_safe_float(item.get("y")) for item in series]
    basic_stats = _compute_basic_stats(values)
    max_period = _period_of_value(series, basic_stats.get("max", 0))
    min_period = _period_of_value(series, basic_stats.get("min", 0))
    median_period = _period_of_value(series, basic_stats.get("median", 0))

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
            net_growth_total = sum(cat_growths)

            cat_growth = cat_growths[idx] if idx < len(cat_growths) else 0.0
            growth_contrib_signed = (cat_growth / net_growth_total * 100) if net_growth_total else 0.0
            growth_contrib_abs = (abs(cat_growth) / total_abs_growth * 100) if total_abs_growth else 0.0

            categories.append({
                "name": label,
                "series": data,
                "trendDirection": _trend_direction(v),
                "volatility": _compute_volatility(v),
                "maxGrowthPeriod": max_growth_cat,
                "minGrowthPeriod": min_growth_cat,
                "peakValley": peak_valley_cat,
                "sharePct": share_pct,
                "growthValue": cat_growth,
                "growthContributionPctSigned": growth_contrib_signed,
                "growthContributionPctAbs": growth_contrib_abs
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

    overview_sentence = f"{metric_label}趋势范围：{since or 'N/A'} ~ {until or 'N/A'}，时间粒度为{gran_label}，整体趋势{trend_direction}。"
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
        "natural_fragments": {"overview_sentence": overview_sentence}
    }


def _build_metric_semantics(metric: str) -> Dict[str, str]:
    metric_cn = METRIC_LABELS_CN.get(metric, metric)

    if metric == "sales_amount":
        unit = "元"
        definition = "销售额=时间范围内订单行金额合计（Σ UnitPrice×Quantity）"
        share_denominator = "总体销售额"
        trend_growth_definition = "趋势型增长率=（本期销售额-上期销售额）/上期销售额 × 100%"
    elif metric == "order_count":
        unit = "笔"
        definition = "订单量=去重订单数（COUNT DISTINCT InvoiceId）"
        share_denominator = "总体订单量"
        trend_growth_definition = "趋势型增长率=（本期订单量-上期订单量）/上期订单量 × 100%"
    else:
        unit = "元/笔"
        definition = "客单价=销售额/订单量（总销售额÷总订单数）"
        share_denominator = "维度结构展示时按该指标汇总口径计算"
        trend_growth_definition = "趋势型增长率=（本期客单价-上期客单价）/上期客单价 × 100%"

    return {
        "metric_name": metric_cn,
        "metric_unit": unit,
        "metric_definition": definition,
        "share_denominator": share_denominator,
        "trend_growth_definition": trend_growth_definition,
        "value_interpretation": f"凡未特别说明，数值字段均表示“{metric_cn}”，单位“{unit}”。",
        "no_revalidation_note": "口径已在上文固定，禁止对占比与增长率定义进行二次验证或改写。"
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
    return "\n".join([f"{item.get('x')}: {_format_metric_value(metric, _safe_float(item.get('y')))}" for item in series])


def _build_selected_dimensions_block(dims: List[str]) -> Dict[str, Any]:
    selected_keys: List[str] = [d for d in (dims or []) if d in DIMENSION_LABELS_CN and d != "total"]
    selected_titles: List[str] = [DIMENSION_LABELS_CN[k] for k in selected_keys]
    selected_h2_lines = "\n".join([f"## {t}" for t in selected_titles]) if selected_titles else "（本次未选择维度）"
    selected_titles_joined = "、".join(selected_titles) if selected_titles else "无"
    return {
        "selected_keys": selected_keys,
        "selected_titles": selected_titles,
        "selected_h2_lines": selected_h2_lines,
        "selected_titles_joined": selected_titles_joined
    }


def _build_markdown_constraints_text(selected_dim_titles: List[str]) -> str:
    base = (
        "1) 仅输出 Markdown 正文，不要输出解释、前言、代码块围栏或额外说明。\n"
        "2) 一级标题必须严格且按以下顺序输出，名称必须完全一致：\n"
        "# 概览\n"
        "# 维度关键发现\n"
        "# 原因分析\n"
        "# 建议\n"
        "3) 除“维度关键发现”外，其他一级标题下不要创建维度型二级标题。\n"
    )
    if selected_dim_titles:
        dim_lines = "\n".join([f"## {t}" for t in selected_dim_titles])
        dim_part = (
            "4) 在“维度关键发现”章节下，只能使用以下二级标题（名称必须完全一致）：\n"
            f"{dim_lines}\n"
            "5) 不得输出未在上述列表中的维度二级标题。\n"
            "6) 若某个允许维度数据不足，可在该标题下说明“数据不足”，但不能改标题、不能删标题。\n"
        )
    else:
        dim_part = (
            "4) 本次未选择维度。在“维度关键发现”下不要输出二级标题，可写“本次未选择维度分析”。\n"
            "5) 不得新增任何维度型二级标题。\n"
        )
    tail = "7) 不要输出任何图片占位符（如 {{image:...}}）,图片由系统后处理插入。"
    return base + dim_part + tail


def _build_report_type_contract(report_type: str) -> Dict[str, str]:
    if report_type == "statistical":
        return {
            "report_type_name": "统计型",
            "analysis_goal": "识别总体规模、结构分布、TopN贡献和集中度特征。",
            "focus_points": "总量、占比、TopN、其他、集中度、维度对比",
            "overview_rule": "先概述总体规模，再说明结构分布与头部集中情况。",
            "reasoning_rule": "重点解释结构差异、头部贡献与潜在业务含义。",
            "advice_rule": "建议围绕资源配置、重点维度经营、长尾优化展开。"
        }
    return {
        "report_type_name": "趋势型",
        "analysis_goal": "识别整体趋势方向、波动特征、异常节点及维度驱动因素。",
        "focus_points": "趋势、拐点、峰谷、波动、增长贡献、异常期",
        "overview_rule": "先判断整体走势，再说明关键拐点与阶段变化。",
        "reasoning_rule": "重点解释维度驱动、波动来源及异常期可能原因。",
        "advice_rule": "建议围绕趋势延续、风险预警、波动治理展开。"
    }


def _build_report_style_contract(report_style: Optional[str]) -> Dict[str, str]:
    style = (report_style or "standard").strip().lower()
    contracts = {
        "simple": {
            "style_name": "简明分析性",
            "writing_goal": "先结论后展开，用最少文字表达最关键发现。",
            "focus_rule": "优先输出3-5条关键结论，每条尽量附数字证据。",
            "reasoning_rule": "只保留必要解释，避免冗长推演。",
            "advice_rule": "建议简洁明确，不超过3-5条。",
            "language_rule": "语言精炼，管理层快速可读。"
        },
        "attribution": {
            "style_name": "归因解析型",
            "writing_goal": "不仅描述现象，还要解释变化由谁驱动、为什么发生。",
            "focus_rule": "必须区分主因、次因，并说明结构占比与关键贡献来源。",
            "reasoning_rule": "优先解释业务机制；无法验证因果必须标注“推测”。",
            "advice_rule": "建议需与原因分析一一对应。",
            "language_rule": "强调因果链路和证据对应。"
        },
        "forecast": {
            "style_name": "预测建议型",
            "writing_goal": "在现有数据基础上做方向判断，并提出可执行动作。",
            "focus_rule": "必须包含短期/中期走势、风险点与触发条件。",
            "reasoning_rule": "预测必须基于已给数据，不得写成确定事实。",
            "advice_rule": "建议要含优先级、动作对象、预期影响。",
            "language_rule": "偏经营决策表达，强调行动性。"
        },
        "standard": {
            "style_name": "综合标准型",
            "writing_goal": "兼顾概览、发现、归因和建议，保持完整平衡。",
            "focus_rule": "覆盖事实、分析和建议，不偏废。",
            "reasoning_rule": "结论与证据必须对应。",
            "advice_rule": "建议与关键发现保持一致。",
            "language_rule": "专业、完整、稳定。"
        }
    }
    return contracts.get(style, contracts["standard"])


def _fallback_template() -> str:
    return (
        "【角色与场景】\n"
        "你是一位{role_context[analyst_level]}，负责{role_context[domain]}的{role_context[decision_type]}分析。\n\n"
        "【类型与风格】\n"
        "- 报告类型：{report_type_contract[report_type_name]}\n"
        "- 报告风格：{report_style_contract[style_name]}\n"
        "- 风格目标：{report_style_contract[writing_goal]}\n\n"
        "【数据事实】\n"
        "{data_summary[natural_fragments][overview_sentence]}\n\n"
        "【核心数据指标（按{series_granularity_label}）】\n"
        "{total_series_text}\n\n"
        "【维度结构（{dimension_analysis[dim_label]}）】\n"
        "{dim_table}\n\n"
        "【输出要求】\n"
        "格式：{format_requirements[sections]}\n"
        "风格：{format_requirements[tone]}\n"
        "数字格式：{format_requirements[number_format]}\n"
        "字数：{format_requirements[length_limit]}\n\n"
        "【Markdown结构硬约束】\n"
        "{markdown_constraints}"
    )


def build_prompt_bundle(normalized: Dict[str, Any], plots: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    try:
        report_type = normalized.get("reportType", "statistical")
        metric = normalized.get("metric", "sales_amount")
        granularity = normalized.get("granularity", "month")
        top_n = int(normalized.get("topN") or 10)
        since = normalized.get("since")
        until = normalized.get("until")
        dims = normalized.get("dimensions") or ["total"]
        dims = [d for d in dims if d in DIMENSION_LABELS_CN] or ["total"]

        selected_dims_block = _build_selected_dimensions_block(dims)
        markdown_constraints = _build_markdown_constraints_text(selected_dims_block["selected_titles"])

        style_raw = normalized.get("reportStyle")
        report_style = None
        if style_raw is not None:
            s = str(style_raw).strip()
            report_style = REPORT_STYLE_MAP.get(s, s.lower() if s else None)

        style_key = f"{report_type}.{report_style}" if report_style else report_type
        _TEMPLATE_DEBUG_STATE["style_key"] = style_key

        metric_label = METRIC_LABELS_CN.get(metric, metric)
        gran_label = GRANULARITY_LABELS_CN.get(granularity, granularity)
        periods = build_period_range(granularity, since, until)
        metric_semantics = _build_metric_semantics(metric)

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
            "statistical": {},
            "trend": {},
            "llmSummary": {}
        }

        if report_type == "statistical":
            sql, params = build_period_trend(metric, granularity, since, until)
            rows = run_query(sql, params)
            total_series = build_total_series(rows, granularity, periods=periods if periods else None)
            total_metric = _compute_total_metric(metric, granularity, since, until) if metric == "avg_order_value" else sum(_safe_float(item.get("y")) for item in total_series)
            dimension_summaries = [_build_stat_dimension_summary(dim, metric, since, until, top_n) for dim in dims if dim != "total"]

            prompt_data["statistical"] = {"total": total_metric, "dimensions": dimension_summaries}
            prompt_data["llmSummary"]["statistical"] = _build_stat_llm_summary(
                metric, metric_label, granularity, gran_label, since, until, top_n, dims, total_metric, dimension_summaries, total_series
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

            trend_dir = _trend_direction([_safe_float(i.get("y")) for i in series])
            prompt_data["trend"] = {"series": series, "trendDirection": trend_dir, "dimensions": dimension_series}
            prompt_data["llmSummary"]["trend"] = _build_trend_llm_summary(
                metric, metric_label, granularity, gran_label, since, until, top_n, dims, series, trend_dir, dimension_series
            )

        llm_data = (prompt_data.get("llmSummary") or {}).get("statistical" if report_type == "statistical" else "trend") or {}
        role_context = {"analyst_level": "资深数据分析师", "domain": "销售数据", "decision_type": "经营决策", "report_audience": "管理层"}

        basic_stats = llm_data.get("basicStats", {}) if isinstance(llm_data, dict) else {}
        total_sales = _compute_total_metric("sales_amount", granularity, since, until)
        total_orders = _compute_total_metric("order_count", granularity, since, until)
        avg_order = total_sales / total_orders if total_orders else 0.0

        if metric == "sales_amount":
            total_value_num = total_sales
        elif metric == "order_count":
            total_value_num = total_orders
        else:
            total_value_num = avg_order

        key_metrics = {
            "total_value_text": _format_metric_value(metric, total_value_num),
            "transaction_count": f"{total_orders:,.0f}",
            "avg_order_value_text": _format_metric_value("avg_order_value", avg_order),
            "period_mean_text": _format_metric_value(metric, basic_stats.get("mean", 0.0)),
            "period_max_text": _format_metric_value(metric, basic_stats.get("max", 0.0)),
            "period_max_period": llm_data.get("maxPeriod") or "N/A",
            "period_min_text": _format_metric_value(metric, basic_stats.get("min", 0.0)),
            "period_min_period": llm_data.get("minPeriod") or "N/A",
            "period_median_text": _format_metric_value(metric, basic_stats.get("median", 0.0)),
            "period_median_period": llm_data.get("medianPeriod") or "N/A"
        }

        if report_type == "statistical":
            task_definition = {
                "analysis_type": "统计型",
                "focus": f"{metric_label}结构与Top{top_n}贡献",
                "depth": "结构、占比、集中度与对比"
            }
            dim_summaries = llm_data.get("dimensionsSummary") or []
            dim_label = "、".join([d.get("dimensionLabel") for d in dim_summaries if isinstance(d, dict) and d.get("dimensionLabel")]) or "维度"
            dim_table = _build_dim_table_texts(dim_summaries, metric)
        else:
            task_definition = {
                "analysis_type": "趋势型",
                "focus": f"{metric_label}趋势变化与波动诊断",
                "depth": "趋势方向、波动、异常与结构差异"
            }
            dim_summaries = llm_data.get("dimensionsSummary") or []
            dim_label = "、".join([d.get("dimensionLabel") for d in dim_summaries if isinstance(d, dict) and d.get("dimensionLabel")]) or "维度"
            dim_table = _build_trend_dim_table_texts(dim_summaries, metric)

        report_type_contract = _build_report_type_contract(report_type)
        report_style_contract = _build_report_style_contract(report_style)

        format_requirements = {
            "sections": "概览/维度关键发现/原因分析/建议",
            "tone": f"{report_type_contract['report_type_name']} + {report_style_contract['style_name']}；{report_style_contract['writing_goal']}",
            "number_format": "金额保留2位小数，比例保留2位小数",
            "length_limit": "600-1000字"
        }

        total_series_text = _build_total_series_text((llm_data.get("series") if isinstance(llm_data, dict) else []) or [], metric)

        template_payload = {
            "role_context": role_context,
            "task_definition": task_definition,
            "report_type_contract": report_type_contract,
            "report_style_contract": report_style_contract,
            "data_summary": llm_data,
            "key_metrics": key_metrics,
            "metric_semantics": metric_semantics,
            "dimension_analysis": {
                "dim_label": dim_label,
                "selected_titles_joined": selected_dims_block.get("selected_titles_joined", "无"),
                "selected_h2_lines": selected_dims_block.get("selected_h2_lines", "")
            },
            "dim_table": dim_table,
            "format_requirements": format_requirements,
            "series_granularity_label": gran_label,
            "total_series_text": total_series_text,
            "markdown_constraints": markdown_constraints
        }

        templates = load_templates()
        template_text = pick_template(style_key, templates)
        if not (template_text or "").strip():
            template_text = pick_template(report_type, templates)
        if not (template_text or "").strip():
            template_text = pick_template("default", templates)
        if not (template_text or "").strip():
            template_text = _fallback_template()
            _TEMPLATE_DEBUG_STATE["used_fallback_default"] = True
            _TEMPLATE_DEBUG_STATE["fallback_reason"] = "empty_template"
            _TEMPLATE_DEBUG_STATE["selected_by"] = _TEMPLATE_DEBUG_STATE.get("selected_by") or "builtin_fallback"
            _TEMPLATE_DEBUG_STATE["selected_template_len"] = len(template_text)

        prompt_text = render_template(template_text, template_payload)
        unresolved_count = _count_unresolved_placeholders(prompt_text)
        _TEMPLATE_DEBUG_STATE["unresolved_placeholder_count"] = unresolved_count

        if (not prompt_text.strip()) or _has_unresolved_placeholders(prompt_text):
            fallback_tpl = _fallback_template()
            fallback_prompt = render_template(fallback_tpl, template_payload)
            fallback_unresolved = _count_unresolved_placeholders(fallback_prompt)
            if fallback_prompt.strip() and fallback_unresolved <= unresolved_count:
                prompt_text = fallback_prompt
                _TEMPLATE_DEBUG_STATE["used_fallback_default"] = True
                _TEMPLATE_DEBUG_STATE["fallback_reason"] = "render_failed_or_unresolved_placeholders"
                _TEMPLATE_DEBUG_STATE["selected_by"] = "builtin_fallback"
                _TEMPLATE_DEBUG_STATE["selected_template_len"] = len(fallback_tpl)
                _TEMPLATE_DEBUG_STATE["unresolved_placeholder_count"] = fallback_unresolved

        style_appendix = STYLE_APPENDIX.get(style_key, "")
        _TEMPLATE_DEBUG_STATE["style_appendix_len"] = len(style_appendix or "")
        if style_appendix:
            prompt_text = prompt_text.rstrip() + "\n\n" + style_appendix.strip() + "\n"

        _TEMPLATE_DEBUG_STATE["rendered_prompt_len"] = len(prompt_text or "")
        return {
            "prompt": prompt_text,
            "promptData": prompt_data,
            "frontendSchema": get_frontend_schema(),
            "templateDebug": get_template_debug_state()
        }

    except Exception as e:
        _TEMPLATE_DEBUG_STATE["render_ok"] = False
        _TEMPLATE_DEBUG_STATE["render_error"] = repr(e)
        fallback_prompt = (
            "【角色与场景】\n"
            "你是一位资深数据分析师。\n\n"
            "【错误说明】\n"
            "Prompt 生成失败，请检查模板与数据配置。\n"
        )
        return {
            "prompt": fallback_prompt,
            "promptData": {"summary": {}, "llmSummary": {}, "charts": {"count": 0, "items": []}, "statistical": {}, "trend": {}},
            "frontendSchema": get_frontend_schema(),
            "templateDebug": get_template_debug_state()
        }