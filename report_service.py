from typing import List, Dict, Any, Tuple, Optional
import io
import base64
from datetime import datetime, timedelta, date, time
from dateutil import parser as dateparser
from dateutil.relativedelta import relativedelta
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import re
from decimal import Decimal
from utils import get_db_connection

# ---------- 时间表达式 ----------

def invoice_datetime_expr() -> str:
    return "i.InvoiceDate"

def granularity_expression(gran: str) -> str:
    dt = invoice_datetime_expr()
    if gran == 'day':
        return f"DATE_FORMAT({dt}, '%Y-%m-%d')"
    if gran == 'week':
        return f"DATE_FORMAT(DATE_SUB({dt}, INTERVAL WEEKDAY({dt}) DAY), '%Y-%m-%d')"
    if gran == 'month':
        return f"DATE_FORMAT({dt}, '%Y-%m')"
    if gran == 'quarter':
        return f"CONCAT(YEAR({dt}), '-Q', QUARTER({dt}))"
    if gran == 'year':
        return f"DATE_FORMAT({dt}, '%Y')"
    raise ValueError(f"unknown granularity: {gran}")

def metric_sql(metric: str) -> str:
    if metric == 'sales_amount':
        return "IFNULL(SUM(i.Total), 0) AS value"
    if metric == 'order_count':
        return "COUNT(DISTINCT i.InvoiceId) AS value"
    if metric == 'avg_order_value':
        return "IFNULL(SUM(i.Total) / NULLIF(COUNT(DISTINCT i.InvoiceId), 0), 0) AS value"
    raise ValueError(f"unknown metric: {metric}")

# 维度查询（join 到明细表）必须避免重复计数
# - sales_amount 用 il.UnitPrice * il.Quantity
# - order_count 用 DISTINCT invoice
# - avg_order_value 用分子(行金额和)/分母(发票数)
def metric_sql_with_lines(metric: str) -> str:
    if metric == 'sales_amount':
        return "IFNULL(SUM(il.UnitPrice * il.Quantity), 0) AS value"
    if metric == 'order_count':
        return "COUNT(DISTINCT i.InvoiceId) AS value"
    if metric == 'avg_order_value':
        return "IFNULL(SUM(il.UnitPrice * il.Quantity) / NULLIF(COUNT(DISTINCT i.InvoiceId), 0), 0) AS value"
    raise ValueError(f"unknown metric: {metric}")

# ---------- 维度表达式 ----------

def dimension_expression(dimension: str) -> Tuple[str, str]:
    if dimension == 'genre':
        return "g.Name", "genre"
    if dimension == 'artist':
        return "ar.Name", "artist"
    if dimension == 'country':
        return "c.Country", "country"
    if dimension == 'city':
        return "c.City", "city"
    if dimension == 'customer':
        return "CONCAT(c.FirstName,' ',c.LastName)", "customer"
    if dimension == 'employee':
        return "CONCAT(e.FirstName,' ',e.LastName)", "employee"
    raise ValueError(f"unknown dimension: {dimension}")

# ---------- 时间范围工具 ----------

_YEAR_RE = re.compile(r"^(\d{4})$")
_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
_DAY_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$")

def _parse_datetime_input(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())

    v = str(value).strip()
    if not v:
        return None

    m = _YEAR_RE.match(v)
    if m:
        return datetime(int(m.group(1)), 1, 1)

    m = _MONTH_RE.match(v)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), 1)

    m = _DAY_RE.match(v)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    m = _QUARTER_RE.match(v)
    if m:
        year = int(m.group(1))
        q = int(m.group(2))
        month = (q - 1) * 3 + 1
        return datetime(year, month, 1)

    try:
        return dateparser.parse(v)
    except Exception:
        return None

def _normalize_period_start(granularity: str, dt: datetime) -> datetime:
    if granularity == "day":
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)
    if granularity == "week":
        start = dt - timedelta(days=dt.weekday())
        return start.replace(hour=0, minute=0, second=0, microsecond=0)
    if granularity == "month":
        return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if granularity == "quarter":
        month = ((dt.month - 1) // 3) * 3 + 1
        return dt.replace(month=month, day=1, hour=0, minute=0, second=0, microsecond=0)
    if granularity == "year":
        return dt.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return dt

def _period_step(granularity: str):
    if granularity == "day":
        return relativedelta(days=1)
    if granularity == "week":
        return relativedelta(weeks=1)
    if granularity == "month":
        return relativedelta(months=1)
    if granularity == "quarter":
        return relativedelta(months=3)
    if granularity == "year":
        return relativedelta(years=1)
    return relativedelta(days=1)

def format_period_label(granularity: str, dt: datetime) -> str:
    if granularity == "month":
        return dt.strftime("%Y-%m")
    if granularity == "quarter":
        quarter = (dt.month - 1) // 3 + 1
        return f"{dt.year}-Q{quarter}"
    if granularity == "year":
        return dt.strftime("%Y")
    return dt.strftime("%Y-%m-%d")

def build_period_range(granularity: str, since=None, until=None) -> List[str]:
    if not since or not until:
        return []
    start_dt = _parse_datetime_input(since)
    end_dt = _parse_datetime_input(until)
    if not start_dt or not end_dt:
        return []

    current = _normalize_period_start(granularity, start_dt)
    end_dt = _normalize_period_start(granularity, end_dt)
    step = _period_step(granularity)
    periods: List[str] = []
    while current <= end_dt:
        periods.append(format_period_label(granularity, current))
        current = current + step
    return periods

def _normalize_since_until(since: Any, until: Any) -> Tuple[Optional[str], Optional[str]]:
    s_dt = _parse_datetime_input(since) if since else None
    u_dt = _parse_datetime_input(until) if until else None

    if s_dt:
        s_dt = datetime.combine(s_dt.date(), time.min)
    if u_dt:
        u_dt = datetime.combine(u_dt.date(), time.max)

    s = s_dt.strftime("%Y-%m-%d %H:%M:%S") if s_dt else None
    u = u_dt.strftime("%Y-%m-%d %H:%M:%S") if u_dt else None
    return s, u

def normalize_time_range_for_debug(since: Any, until: Any) -> Dict[str, Optional[str]]:
    s, u = _normalize_since_until(since, until)
    return {"since": s, "until": u}

# ---------- 基础执行 ----------

def _normalize_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value

def _normalize_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in rows:
        d: Dict[str, Any] = {}
        for k, v in r.items():
            d[k] = _normalize_value(v)
        out.append(d)
    return out

def run_query(sql: str, params: List[Any]) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    if not conn:
        raise RuntimeError("数据库连接失败")
    cursor = conn.cursor(dictionary=True)
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    conn.close()
    return _normalize_rows(rows)

# ---------- 趋势查询 ----------

def build_period_trend(metric: str, granularity: str, since=None, until=None) -> Tuple[str, List[Any]]:
    params = []
    where = []
    dt = invoice_datetime_expr()

    since_norm, until_norm = _normalize_since_until(since, until)

    if since_norm:
        where.append(f"{dt} >= %s")
        params.append(since_norm)
    if until_norm:
        where.append(f"{dt} <= %s")
        params.append(until_norm)

    where_sql = "WHERE " + " AND ".join(where) if where else ""
    period_expr = granularity_expression(granularity)

    sql = f"""
    SELECT {period_expr} AS period,
           {metric_sql(metric)}
    FROM Invoice i
    {where_sql}
    GROUP BY period
    ORDER BY period ASC
    """
    return sql, params

def build_dimension_trend(metric: str, granularity: str, dimension: str, since=None, until=None) -> Tuple[str, List[Any]]:
    params = []
    where = []
    dt = invoice_datetime_expr()

    since_norm, until_norm = _normalize_since_until(since, until)

    if since_norm:
        where.append(f"{dt} >= %s")
        params.append(since_norm)
    if until_norm:
        where.append(f"{dt} <= %s")
        params.append(until_norm)

    where_sql = "WHERE " + " AND ".join(where) if where else ""
    period_expr = granularity_expression(granularity)
    dim_expr, dim_alias = dimension_expression(dimension)

    from_clause = """
    FROM Invoice i
    JOIN Customer c ON i.CustomerId = c.CustomerId
    LEFT JOIN Employee e ON c.SupportRepId = e.EmployeeId
    JOIN InvoiceLine il ON i.InvoiceId = il.InvoiceId
    JOIN Track t ON il.TrackId = t.TrackId
    JOIN Album al ON t.AlbumId = al.AlbumId
    JOIN Artist ar ON al.ArtistId = ar.ArtistId
    JOIN Genre g ON t.GenreId = g.GenreId
    """

    sql = f"""
    SELECT {period_expr} AS period,
           {dim_expr} AS {dim_alias},
           {metric_sql_with_lines(metric)}
    {from_clause}
    {where_sql}
    GROUP BY period, {dim_alias}
    ORDER BY period ASC, value DESC
    """
    return sql, params

# ---------- 图表工具 ----------

def _encode_png(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    data = buf.read()
    return base64.b64encode(data).decode('ascii')

def parse_period(granularity: str, value: Any):
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time())
    else:
        v = str(value).strip()

        if _QUARTER_RE.match(v):
            year, q = v.split("-Q")
            month = (int(q) - 1) * 3 + 1
            return datetime(int(year), month, 1)

        if _YEAR_RE.match(v):
            return datetime(int(v), 1, 1)

        m = _MONTH_RE.match(v)
        if m:
            return datetime(int(m.group(1)), int(m.group(2)), 1)

        m = _DAY_RE.match(v)
        if m:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))

        try:
            dt = dateparser.parse(v)
        except Exception:
            return None

    if not dt:
        return None

    if granularity == "month":
        return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if granularity == "quarter":
        month = ((dt.month - 1) // 3) * 3 + 1
        return dt.replace(month=month, day=1, hour=0, minute=0, second=0, microsecond=0)
    if granularity == "year":
        return dt.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return dt

def normalize_period_label(granularity: str, value: Any) -> str:
    dt = parse_period(granularity, value)
    if dt:
        return format_period_label(granularity, dt)
    return str(value)

def sort_periods(periods: List[str], granularity: str) -> List[str]:
    return sorted(periods, key=lambda p: parse_period(granularity, p) or p)

def format_value(value: Any) -> str:
    try:
        f_val = float(value)
        if f_val.is_integer():
            return str(int(f_val))
        return f"{f_val:.2f}"
    except Exception:
        return str(value)

def generate_line_chart(series: List[Dict[str, Any]], granularity: str, y_label: str = "value") -> str:
    fig, ax = plt.subplots(figsize=(12, 6))
    for s in series:
        xs, ys = [], []
        for p in s['data']:
            dt = parse_period(granularity, p.get('x'))
            if dt:
                xs.append(dt)
                ys.append(float(p.get('y') or 0))
        if xs:
            ax.plot(xs, ys, marker='o', label=s.get('label', 'series'))
    ax.set_xlabel("period")
    ax.set_ylabel(y_label)
    ax.legend(loc='best')
    locator = mdates.AutoDateLocator()
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    fig.autofmt_xdate()
    return _encode_png(fig)

def generate_grouped_bar_chart(
    rows: List[Dict[str, Any]],
    granularity: str,
    period_key: str = "period",
    dim_key: str = "dimension",
    categories: Optional[List[str]] = None,
    periods: Optional[List[str]] = None,
    y_label: str = "value",
    x_label: Optional[str] = "period"
) -> str:
    if not rows:
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.text(0.5, 0.5, "no data", ha="center", va="center")
        ax.axis('off')
        return _encode_png(fig)

    if periods is None:
        periods = sort_periods(list({str(r.get(period_key)) for r in rows if r.get(period_key) is not None}), granularity)
    else:
        periods = [normalize_period_label(granularity, p) for p in periods]

    if categories is None:
        categories = list(dict.fromkeys([r.get(dim_key) for r in rows if r.get(dim_key) is not None]))

    values_map: Dict[str, Dict[str, float]] = {}
    for r in rows:
        dim_val = r.get(dim_key)
        period_val = normalize_period_label(granularity, r.get(period_key))
        value = float(r.get("value") or 0)
        values_map.setdefault(dim_val, {})[period_val] = value

    fig, ax = plt.subplots(figsize=(12, 6))
    x = np.arange(len(periods))
    count = max(len(categories), 1)
    width = 0.8 / count

    for idx, cat in enumerate(categories):
        offsets = x + (idx - (count - 1) / 2) * width
        heights = [values_map.get(cat, {}).get(p, 0) for p in periods]
        bars = ax.bar(offsets, heights, width, label=str(cat))
        for bar, height in zip(bars, heights):
            ax.annotate(
                format_value(height),
                xy=(bar.get_x() + bar.get_width() / 2, height),
                xytext=(0, 3),
                textcoords="offset points",
                ha='center',
                va='bottom',
                fontsize=8
            )

    if x_label is not None:
        ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.set_xticks(x)
    ax.set_xticklabels(periods, rotation=45, ha='right')
    ax.legend(loc='best')
    fig.tight_layout()
    return _encode_png(fig)

# ---------- 聚合 ----------

def build_aggregation_query(payload: Dict[str, Any]) -> Tuple[str, List[Any]]:
    dims: List[str] = payload.get('dimensions') or []
    report_type = payload.get('reportType')
    metric = payload['metric']
    params: List[Any] = []
    where_clauses: List[str] = []

    dt = invoice_datetime_expr()
    since_norm, until_norm = _normalize_since_until(payload.get('since'), payload.get('until'))
    if since_norm:
        where_clauses.append(f"{dt} >= %s")
        params.append(since_norm)
    if until_norm:
        where_clauses.append(f"{dt} <= %s")
        params.append(until_norm)

    filters = payload.get('filters') or {}
    for k, vals in filters.items():
        if not vals:
            continue
        placeholders = ','.join(['%s'] * len(vals))
        params.extend(vals)

        if k == 'genre':
            where_clauses.append(f"g.Name IN ({placeholders})")
        elif k == 'artist':
            where_clauses.append(f"ar.Name IN ({placeholders})")
        elif k == 'country':
            where_clauses.append(f"c.Country IN ({placeholders})")
        elif k == 'city':
            where_clauses.append(f"c.City IN ({placeholders})")
        elif k == 'customer':
            where_clauses.append(f"CONCAT(c.FirstName,' ',c.LastName) IN ({placeholders})")
        elif k == 'employee':
            where_clauses.append(f"CONCAT(e.FirstName,' ',e.LastName) IN ({placeholders})")
        else:
            where_clauses.append(f"{k} IN ({placeholders})")

    select_parts: List[str] = []
    group_parts: List[str] = []

    if report_type == 'trend':
        gran = payload.get('granularity')
        if not gran:
            raise ValueError("granularity required for trend reports")
        period_expr = granularity_expression(gran)
        select_parts.append(f"{period_expr} AS period")
        group_parts.append("period")

    for d in dims:
        if d == 'genre':
            select_parts.append("g.Name AS genre")
            group_parts.append("genre")
        elif d == 'artist':
            select_parts.append("ar.Name AS artist")
            group_parts.append("artist")
        elif d == 'country':
            select_parts.append("c.Country AS country")
            group_parts.append("country")
        elif d == 'city':
            select_parts.append("c.City AS city")
            group_parts.append("city")
        elif d == 'customer':
            select_parts.append("CONCAT(c.FirstName,' ',c.LastName) AS customer")
            group_parts.append("customer")
        elif d == 'employee':
            select_parts.append("CONCAT(e.FirstName,' ',e.LastName) AS employee")
            group_parts.append("employee")

    select_parts.append(metric_sql_with_lines(metric))

    from_clause = """
    FROM Invoice i
    JOIN Customer c ON i.CustomerId = c.CustomerId
    LEFT JOIN Employee e ON c.SupportRepId = e.EmployeeId
    JOIN InvoiceLine il ON i.InvoiceId = il.InvoiceId
    JOIN Track t ON il.TrackId = t.TrackId
    JOIN Album al ON t.AlbumId = al.AlbumId
    JOIN Artist ar ON al.ArtistId = ar.ArtistId
    JOIN Genre g ON t.GenreId = g.GenreId
    """

    sql = f"SELECT {', '.join(select_parts)} {from_clause}"
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    if group_parts:
        sql += " GROUP BY " + ", ".join(group_parts)
    sql += " ORDER BY value DESC"

    if payload.get('topN') and report_type == 'statistical':
        try:
            n = int(payload.get('topN'))
            sql += f" LIMIT {n}"
        except Exception:
            pass

    return sql, params

def run_aggregation(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    if not conn:
        raise RuntimeError("数据库连接失败")

    sql, params = build_aggregation_query(payload)
    cursor = conn.cursor(dictionary=True)
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    conn.close()

    return _normalize_rows(rows)

def select_top_categories(rows: List[Dict[str, Any]], dim_key: str, top_n: int) -> List[Any]:
    if not rows:
        return []
    totals: Dict[Any, float] = {}
    for r in rows:
        dim_val = r.get(dim_key)
        totals[dim_val] = totals.get(dim_val, 0) + float(r.get("value") or 0)
    sorted_items = sorted(totals.items(), key=lambda x: x[1], reverse=True)
    return [k for k, _ in sorted_items[:top_n]] if top_n else [k for k, _ in sorted_items]

def build_series_by_dimension(
    rows: List[Dict[str, Any]],
    dim_key: str,
    granularity: str,
    periods: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    series_map: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        label = r.get(dim_key)
        x_val = normalize_period_label(granularity, r.get("period"))
        series_map.setdefault(label, []).append({"x": x_val, "y": r.get("value")})

    if periods:
        norm_periods = [normalize_period_label(granularity, p) for p in periods]
        for label, data in series_map.items():
            existing = {normalize_period_label(granularity, p.get("x")): p.get("y") for p in data}
            series_map[label] = [{"x": p, "y": existing.get(p, 0)} for p in norm_periods]
    else:
        for data in series_map.values():
            data.sort(key=lambda p: parse_period(granularity, p.get("x")) or p.get("x"))

    return [{"label": k, "data": v} for k, v in series_map.items()]

def build_total_series(
    rows: List[Dict[str, Any]],
    granularity: str,
    periods: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    data = [{"x": normalize_period_label(granularity, r.get("period")), "y": r.get("value")} for r in rows]

    if periods:
        norm_periods = [normalize_period_label(granularity, p) for p in periods]
        existing = {normalize_period_label(granularity, p.get("x")): p.get("y") for p in data}
        data = [{"x": p, "y": existing.get(p, 0)} for p in norm_periods]
    else:
        data.sort(key=lambda p: parse_period(granularity, p.get("x")) or p.get("x"))
    return data

def generate_pie_chart(labels: List[str], values: List[float]) -> str:
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.pie(values, labels=labels, autopct='%1.1f%%', startangle=90)
    ax.axis('equal')
    ax.legend(labels, loc='center left', bbox_to_anchor=(1.0, 0.5))
    return _encode_png(fig)