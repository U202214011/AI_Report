from typing import Any, Dict, List, Optional, Tuple

from services.report_service import (
    build_dimension_trend,
    build_period_trend,
    build_series_by_dimension,
    build_total_series,
    run_aggregation,
    run_query,
    select_top_categories,
)


def fetch_total_series(
    metric: str, granularity: str, since: Optional[str], until: Optional[str], periods: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    sql, params = build_period_trend(metric, granularity, since, until)
    rows = run_query(sql, params)
    return build_total_series(rows, granularity, periods=periods if periods else None)


def aggregate_total_metric(metric: str, granularity: str, since: Optional[str], until: Optional[str]) -> List[Dict[str, Any]]:
    return run_aggregation({
        "reportType": "statistical",
        "metric": metric,
        "dimensions": [],
        "timeGranularity": granularity,
        "since": since,
        "until": until,
    })


def aggregate_dimension_metric(metric: str, dim: str, since: Optional[str], until: Optional[str]) -> List[Dict[str, Any]]:
    return run_aggregation({
        "reportType": "statistical",
        "metric": metric,
        "dimensions": [dim],
        "since": since,
        "until": until,
    })


def fetch_dimension_rows_for_trend(
    metric: str, granularity: str, dim: str, since: Optional[str], until: Optional[str]
) -> List[Dict[str, Any]]:
    sql, params = build_dimension_trend(metric, granularity, dim, since, until)
    return run_query(sql, params)


def pick_top_categories(rows: List[Dict[str, Any]], dim_key: str, top_n: int) -> List[str]:
    return select_top_categories(rows, dim_key, top_n)


def group_series_by_dimension(
    rows: List[Dict[str, Any]], dim_key: str, granularity: str, periods: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    return build_series_by_dimension(rows, dim_key, granularity, periods=periods if periods else None)
