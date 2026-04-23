from typing import Dict, Any, List, Optional
import json
import os
import re
import numpy as np
from decimal import Decimal
from datetime import datetime
from dateutil.relativedelta import relativedelta
from services.report_service import build_period_range
from services.prompting import (
    aggregate_dimension_metric,
    aggregate_total_metric,
    build_format_requirements,
    build_markdown_constraints_text,
    build_report_style_contract,
    build_report_type_contract,
    build_selected_dimensions_block,
    fetch_dimension_rows_for_trend,
    fetch_total_series,
    group_series_by_dimension,
    pick_top_categories,
)
from models.schema_config import METRICS, DIMENSIONS, ROLE_CONTEXT

# ---------- 从 schema_config 动态生成映射字典 ----------
METRIC_LABELS_CN    = {k: v["label_cn"] for k, v in METRICS.items()}
DIMENSION_LABELS_CN = {k: v["label_cn"] for k, v in DIMENSIONS.items()}

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

"""
STYLE_APPENDIX = {
    # 降级为"补充提醒"，主控制放入模板主体
    "statistical.simple": "【补充提醒】简明分析性：简单阐述数据代表意义，先结论，少铺陈，3-5条要点优先。",
    "statistical.attribution": "【补充提醒】归因解析型：重点分析数据背后代表的原因和市场分析，区分主因/次因，无法验证因果需标注'推测'。",
    "statistical.forecast": "【补充提醒】预测建议型：结合数据与市场原因，着重给短中期方向、风险触发条件和优先级建议。",
    "statistical.standard": "【补充提醒】综合标准型：保持概览/发现/原因/建议完整平衡。",
    "trend.simple": "【补充提醒】简明分析性：简单阐述数据代表意义，先给趋势结论，再列关键拐点。",
    "trend.attribution": "【补充提醒】归因解析型：重点分析数据背后代表的原因和市场分析，对各维度的有代表性的具体类别的趋势做原因分析。",
    "trend.forecast": "【补充提醒】预测建议型：结合数据与市场原因，着重阐述趋势判断、风险触发与可执行动作的建议与预测结论。",
    "trend.standard": "【补充提醒】综合标准型：综合覆盖趋势、波动、维度差异与建议。"
}
"""

METRIC_MAP = {alias: k for k, v in METRICS.items() for alias in [k, v["label_cn"]]}
# 补充中文别名（订单量/订单数 等）
METRIC_MAP.update({"订单量": "order_count", "订单数": "order_count"})

GRANULARITY_MAP = {
    "month": "month",
    "月": "month",
    "quarter": "quarter",
    "季": "quarter",
    "季度": "quarter",
    "year": "year",
    "年": "year"
}

DIMENSION_MAP = {k: k for k in DIMENSIONS}
DIMENSION_MAP.update({v["label_cn"]: k for k, v in DIMENSIONS.items()})
# 补充特殊别名（如"音乐流派"→"genre"）
DIMENSION_MAP.update({"音乐流派": "genre"})

GRANULARITY_LABELS_CN = {
    "month": "月",
    "quarter": "季度",
    "year": "年"
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
    # 动态从 schema_config 生成，新增/删除维度或指标只需改 schema_config.py
    metric_labels   = [v["label_cn"] for v in METRICS.values()]
    dim_labels      = [v["label_cn"] for v in DIMENSIONS.values()]
    return {
        "report_type": ["统计型", "趋势型"],
        "report_style": ["简明分析性", "归因解析型", "预测建议型", "综合标准型"],
        "metric": metric_labels,
        "granularity": ["月", "季", "年"],
        "top_n": "int",
        "start_date": "YYYY-MM-DD",
        "end_date": "YYYY-MM-DD",
        "dimensions": dim_labels
    }


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _sum_values(rows: List[Dict[str, Any]]) -> float:
    return sum(_safe_float(r.get("value")) for r in rows)


def _compute_total_metric(metric: str, granularity: str, since: Optional[str], until: Optional[str]) -> float:
    rows = aggregate_total_metric(metric, granularity, since, until)

    if metric != "avg_order_value":
        return _sum_values(rows)

    sales_rows = aggregate_total_metric("sales_amount", granularity, since, until)
    order_rows = aggregate_total_metric("order_count", granularity, since, until)
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
    rows = aggregate_dimension_metric(metric, dim, since, until) or []
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
    top_categories = pick_top_categories(rows, dim, top_n) or []
    top_rows = [r for r in rows if str(r.get(dim)) in top_categories] if top_categories else rows[:]
    other_rows = [r for r in rows if str(r.get(dim)) not in top_categories] if top_categories else []

    ranking = []
    for r in top_rows:
        name = r.get(dim)
        if name is not None:
            name = str(name)  # 确保 name 是字符串
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
        lines.append("口径说明：以上'其他'为除TopN外所有类别的合并项，禁止重新拆分或复算。")
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
            lines.append(f"   - 对该维度总净增长的贡献率（带符号）：{contrib_signed:+.2f}%")
            lines.append(f"   - 对该维度总变化的影响率（绝对值）：{contrib_abs:.2f}%")

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

        # 全量类别序列：只用于计算“该维度总数据”的增长贡献率与影响率
        all_series = dim_block.get("allSeries") or []
        all_cat_growth_map = {}

        for s in all_series:
            label = s.get("label")
            data = s.get("data") or []
            cat_growth = (_safe_float(data[-1].get("y")) - _safe_float(data[0].get("y"))) if data else 0.0
            all_cat_growth_map[label] = cat_growth

        dim_net_growth_total = sum(all_cat_growth_map.values())
        dim_total_abs_growth = sum(abs(v) for v in all_cat_growth_map.values())

        categories = []
        for s in dim_block.get("series", []):   # 这里只展示 TopN
            label = s.get("label")
            data = s.get("data") or []
            v = [_safe_float(p.get("y")) for p in data]
            max_growth_cat = _max_growth_period(data)
            min_growth_cat = _min_growth_period(data)
            peak_valley_cat = _extract_peak_valley(data)
            share_pct = (totals_map.get(label, 0.0) / total_all * 100) if total_all else 0.0

            cat_growth = all_cat_growth_map.get(label, 0.0)

            growth_contrib_signed = (cat_growth / dim_net_growth_total * 100) if dim_net_growth_total else 0.0
            growth_contrib_abs = (abs(cat_growth) / dim_total_abs_growth * 100) if dim_total_abs_growth else 0.0

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
            "topN": top_n,
            "dimensionNetGrowthTotal": dim_net_growth_total,
            "dimensionAbsGrowthTotal": dim_total_abs_growth
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
    cfg = METRICS.get(metric, {})
    metric_cn = cfg.get("label_cn", metric)
    unit = cfg.get("unit", "")
    return {
        "metric_name": metric_cn,
        "metric_unit": unit,
        "metric_definition": cfg.get("definition", ""),
        "share_denominator": cfg.get("share_denominator", ""),
        "trend_growth_definition": cfg.get("trend_growth_definition", ""),
        "value_interpretation": f"凡未特别说明，数值字段均表示'{metric_cn}'，单位'{unit}'。",
        "no_revalidation_note": "口径已在上文固定，禁止对占比与增长率定义进行二次验证或改写。"
    }


def _format_metric_value(metric: str, value: float) -> str:
    cfg = METRICS.get(metric, {})
    fmt = cfg.get("format", "currency")
    unit = cfg.get("unit", "")
    if fmt == "count":
        return f"{value:,.0f} {unit}"
    if fmt == "ratio":
        return f"{value:,.2f} {unit}"
    return f"{value:,.2f} {unit}"


def _build_total_series_text(series: List[Dict[str, Any]], metric: str) -> str:
    if not series:
        return "（无时间序列数据）"
    return "\n".join([f"{item.get('x')}: {_format_metric_value(metric, _safe_float(item.get('y')))}" for item in series])


def _build_selected_dimensions_block(dims: List[str]) -> Dict[str, Any]:
    return build_selected_dimensions_block(dims, DIMENSION_LABELS_CN)


def _build_markdown_constraints_text(selected_dim_titles: List[str]) -> str:
    return build_markdown_constraints_text(selected_dim_titles)


def _build_report_type_contract(report_type: str) -> Dict[str, str]:
    return build_report_type_contract(report_type)


def _build_report_style_contract(report_style: Optional[str]) -> Dict[str, str]:
    return build_report_style_contract(report_style)


def _fallback_template() -> str:
    return (
        "【角色与场景】\n"
        "你是一位{role_context[analyst_level]}，负责{role_context[domain]}的{role_context[decision_type]}分析。\n\n"
        "【类型与风格】\n"
        "报告类型：{report_type_contract[report_type_name]}\n"
        "- 类型目标：{report_type_contract[analysis_goal]}\n"
        "- 类型重点：{report_type_contract[focus_points]}\n"
        "- 概览写法：{report_type_contract[overview_rule]}\n"
        "- 原因分析写法：{report_type_contract[reasoning_rule]}\n"
        "- 建议写法：{report_type_contract[advice_rule]}\n\n"
        "报告风格：{report_style_contract[style_name]}\n"
        "- 风格目标：{report_style_contract[writing_goal]}\n"
        "- 风格侧重点：{report_style_contract[focus_rule]}\n"
        "- 风格推理要求：{report_style_contract[reasoning_rule]}\n"
        "- 风格建议要求：{report_style_contract[advice_rule]}\n"
        "- 风格语言要求：{report_style_contract[language_rule]}\n\n"
        "【数据事实】\n"
        "{data_summary[natural_fragments][overview_sentence]}\n\n"
        "【核心数据指标（按{series_granularity_label}）】\n"
        "{total_series_text}\n\n"
        "【维度结构（{dimension_analysis[dim_label]}）】\n"
        "{dim_table}\n\n"
        "【输出要求】\n"
        "- 结构：{format_requirements[sections]}\n"
        "- 字数：{format_requirements[length_limit]}\n"
        "- 数字格式：{format_requirements[number_format]}\n"
        "- 数据边界：{format_requirements[data_boundary]}\n"
        #"- 证据约束：{format_requirements[evidence_rule]}\n"
        #"- 表达规范：{format_requirements[expression_rule]}\n"
        #"- 不确定性披露：{format_requirements[uncertainty_rule]}\n"
        "- 禁止项：{format_requirements[forbidden_rule]}\n\n"
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
            total_series = fetch_total_series(metric, granularity, since, until, periods=periods if periods else None)
            total_metric = _compute_total_metric(metric, granularity, since, until) if metric == "avg_order_value" else sum(_safe_float(item.get("y")) for item in total_series)
            dimension_summaries = [_build_stat_dimension_summary(dim, metric, since, until, top_n) for dim in dims if dim != "total"]

            prompt_data["statistical"] = {"total": total_metric, "dimensions": dimension_summaries}
            prompt_data["llmSummary"]["statistical"] = _build_stat_llm_summary(
                metric, metric_label, granularity, gran_label, since, until, top_n, dims, total_metric, dimension_summaries, total_series
            )
        else:
            series = fetch_total_series(metric, granularity, since, until, periods=periods if periods else None)

            dimension_series = []
            for dim in [d for d in dims if d != "total"]:
                all_dim_rows = fetch_dimension_rows_for_trend(metric, granularity, dim, since, until)

                totals_info = _compute_dim_totals(all_dim_rows, dim)
                top_categories = pick_top_categories(all_dim_rows, dim, top_n)

                display_dim_rows = all_dim_rows
                if top_categories:
                    display_dim_rows = [r for r in all_dim_rows if r.get(dim) in top_categories]

                all_series_by_dim = group_series_by_dimension(
                    all_dim_rows, dim, granularity, periods=periods if periods else None
                )
                display_series_by_dim = group_series_by_dimension(
                    display_dim_rows, dim, granularity, periods=periods if periods else None
                )

                dimension_series.append({
                    "dimension": dim,
                    "dimensionLabel": DIMENSION_LABELS_CN.get(dim, dim),
                    "topCategories": top_categories,
                    "series": display_series_by_dim,
                    "allSeries": all_series_by_dim,
                    "categoryTotals": totals_info.get("totals"),
                    "totalAll": totals_info.get("total_all")
                })

            trend_dir = _trend_direction([_safe_float(i.get("y")) for i in series])
            prompt_data["trend"] = {"series": series, "trendDirection": trend_dir, "dimensions": dimension_series}
            prompt_data["llmSummary"]["trend"] = _build_trend_llm_summary(
                metric, metric_label, granularity, gran_label, since, until, top_n, dims, series, trend_dir, dimension_series
            )

        llm_data = (prompt_data.get("llmSummary") or {}).get("statistical" if report_type == "statistical" else "trend") or {}
        role_context = ROLE_CONTEXT   # ← 原来是写死的字典，现在从 schema_config 读取

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

        format_requirements = build_format_requirements()

        total_series_text = _build_total_series_text((llm_data.get("series") if isinstance(llm_data, dict) else []) or [], metric)

        # 在 build_prompt_bundle 函数中，template_payload 的组装部分
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
            "markdown_constraints": markdown_constraints,
            "style_instructions": report_style_contract.get("style_instructions", "")
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

        _TEMPLATE_DEBUG_STATE["style_instructions_included"] = True
        _TEMPLATE_DEBUG_STATE["style_instructions_len"] = len(
            (template_payload.get("report_style_contract") or {}).get("style_instructions", "")
        )

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
