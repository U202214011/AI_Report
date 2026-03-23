# ================================================================
# 数据源适配层 —— 换数据库只需改这一个文件
# ================================================================

from typing import Dict, Any, List

# ---------- 角色与业务域（影响 Prompt 生成） ----------
ROLE_CONTEXT = {
    "analyst_level": "资深数据分析师",
    "domain": "音乐流媒体销售",
    "decision_type": "经营决策",
    "report_audience": "管理层"
}

# ---------- 指标定义 ----------
METRICS = {
    "sales_amount": {
        "label_cn": "销售额",
        "unit": "元",
        "sql": "IFNULL(SUM(il.UnitPrice * il.Quantity), 0) AS value",
        "definition": "销售额=时间范围内订单行金额合计",
        "share_denominator": "总体销售额",
        "trend_growth_definition": "趋势型增长率=（本期销售额-上期销售额）/上期销售额 × 100%",
        "format": "currency",   # currency | count | ratio
    },
    "order_count": {
        "label_cn": "订单数",
        "unit": "笔",
        "sql": "COUNT(DISTINCT i.InvoiceId) AS value",
        "definition": "订单量=去重订单数",
        "share_denominator": "总体订单量",
        "trend_growth_definition": "趋势型增长率=（本期订单量-上期订单量）/上期订单量 × 100%",
        "format": "count",
    },
    "avg_order_value": {
        "label_cn": "客单价",
        "unit": "元/笔",
        "sql": "IFNULL(SUM(il.UnitPrice * il.Quantity) / NULLIF(COUNT(DISTINCT i.InvoiceId), 0), 0) AS value",
        "definition": "客单价=销售额/订单量（总销售额÷总订单数）",
        "share_denominator": "维度结构展示时按该指标汇总口径计算",
        "trend_growth_definition": "趋势型增长率=（本期客单价-上期客单价）/上期客单价 × 100%",
        "format": "ratio",
    },
}

# ---------- 维度定义 ----------
# aliases / export_titles 用于导出章节匹配与图片注入
DIMENSIONS = {
    "total": {
        "label_cn": "总量",
        "expr": None,
        "alias": "total",
        "filter_col": None,
        "aliases": ["total", "总量", "总体", "概览"],
        "export_titles": ["总量", "总体", "概览"],
    },
    "genre": {
        "label_cn": "流派",
        "expr": "g.Name",
        "alias": "genre",
        "filter_col": "g.Name",
        "aliases": ["genre", "流派", "音乐流派"],
        "export_titles": ["流派", "音乐流派"],
    },
    "artist": {
        "label_cn": "艺术家",
        "expr": "ar.Name",
        "alias": "artist",
        "filter_col": "ar.Name",
        "aliases": ["artist", "艺术家"],
        "export_titles": ["艺术家"],
    },
    "country": {
        "label_cn": "国家",
        "expr": "c.Country",
        "alias": "country",
        "filter_col": "c.Country",
        "aliases": ["country", "国家"],
        "export_titles": ["国家"],
    },
    "city": {
        "label_cn": "城市",
        "expr": "c.City",
        "alias": "city",
        "filter_col": "c.City",
        "aliases": ["city", "城市"],
        "export_titles": ["城市"],
    },
    "customer": {
        "label_cn": "客户",
        "expr": "CONCAT(c.FirstName,' ',c.LastName)",
        "alias": "customer",
        "filter_col": "CONCAT(c.FirstName,' ',c.LastName)",
        "aliases": ["customer", "客户"],
        "export_titles": ["客户"],
    },
    "employee": {
        "label_cn": "员工",
        "expr": "CONCAT(e.FirstName,' ',e.LastName)",
        "alias": "employee",
        "filter_col": "CONCAT(e.FirstName,' ',e.LastName)",
        "aliases": ["employee", "员工"],
        "export_titles": ["员工"],
    },
}

# ---------- SQL FROM 子句 ----------
FROM_CLAUSE_SIMPLE = """
    FROM Invoice i
    JOIN InvoiceLine il ON i.InvoiceId = il.InvoiceId
"""

FROM_CLAUSE_FULL = """
    FROM Invoice i
    JOIN Customer c ON i.CustomerId = c.CustomerId
    LEFT JOIN Employee e ON c.SupportRepId = e.EmployeeId
    JOIN InvoiceLine il ON i.InvoiceId = il.InvoiceId
    JOIN Track t ON il.TrackId = t.TrackId
    JOIN Album al ON t.AlbumId = al.AlbumId
    JOIN Artist ar ON al.ArtistId = ar.ArtistId
    JOIN Genre g ON t.GenreId = g.GenreId
"""

# ---------- 时间字段 ----------
DATE_FIELD = "i.InvoiceDate"


# ================================================================
# 导出/展示辅助函数 —— routes.py / export_service.py / 其他模块统一复用
# ================================================================

def get_metric_label_map() -> Dict[str, str]:
    return {
        key: conf.get("label_cn", key)
        for key, conf in METRICS.items()
    }


def get_dimension_title_map(include_total: bool = False) -> Dict[str, str]:
    result = {}
    for key, conf in DIMENSIONS.items():
        if key == "total" and not include_total:
            continue
        result[key] = conf.get("label_cn", key)
    return result


def get_dimension_alias_map(include_total: bool = False) -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = {}

    for key, conf in DIMENSIONS.items():
        if key == "total" and not include_total:
            continue

        alias_values: List[str] = []
        alias_values.append(key)

        alias = conf.get("alias")
        if alias:
            alias_values.append(str(alias))

        label_cn = conf.get("label_cn")
        if label_cn:
            alias_values.append(str(label_cn))

        for item in conf.get("aliases", []) or []:
            if item:
                alias_values.append(str(item))

        for item in conf.get("export_titles", []) or []:
            if item:
                alias_values.append(str(item))

        seen = set()
        cleaned = []
        for item in alias_values:
            low = item.strip().lower()
            if not low or low in seen:
                continue
            seen.add(low)
            cleaned.append(item.strip())

        result[key] = cleaned

    return result


def build_selected_dimensions(selected_dim_keys: List[str]) -> List[Dict[str, Any]]:
    alias_map = get_dimension_alias_map(include_total=False)
    title_map = get_dimension_title_map(include_total=False)

    result: List[Dict[str, Any]] = []
    for raw_key in selected_dim_keys or []:
        key = str(raw_key).strip().lower()
        if not key or key == "total":
            continue
        if key not in DIMENSIONS:
            continue

        result.append({
            "key": key,
            "title": title_map.get(key, key),
            "aliases": alias_map.get(key, [key])
        })
    return result