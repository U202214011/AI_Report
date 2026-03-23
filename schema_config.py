# ================================================================
# 数据源适配层 —— 换数据库只需改这一个文件
# ================================================================

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
DIMENSIONS = {
    "total":    {"label_cn": "总量",   "expr": None,                               "alias": "total",    "filter_col": None},
    "genre":    {"label_cn": "流派",   "expr": "g.Name",                           "alias": "genre",    "filter_col": "g.Name"},
    "artist":   {"label_cn": "艺术家", "expr": "ar.Name",                          "alias": "artist",   "filter_col": "ar.Name"},
    "country":  {"label_cn": "国家",   "expr": "c.Country",                        "alias": "country",  "filter_col": "c.Country"},
    "city":     {"label_cn": "城市",   "expr": "c.City",                           "alias": "city",     "filter_col": "c.City"},
    "customer": {"label_cn": "客户",   "expr": "CONCAT(c.FirstName,' ',c.LastName)","alias": "customer", "filter_col": "CONCAT(c.FirstName,' ',c.LastName)"},
    "employee": {"label_cn": "员工",   "expr": "CONCAT(e.FirstName,' ',e.LastName)","alias": "employee", "filter_col": "CONCAT(e.FirstName,' ',e.LastName)"},
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