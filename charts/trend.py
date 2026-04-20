from flask import jsonify
import pandas as pd
import matplotlib.pyplot as plt
from .utils import get_db_connection, fig_to_base64, build_where_clause

def preview_trend(config):
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': '数据库连接失败'}), 500
    gran = config.get('time_granularity', 'month')
    groupby, label_fmt = get_timegroup(gran)

    where_sql, params = build_where_clause(config)
    query = f"""
    SELECT {groupby} period, COUNT(i.InvoiceId) orders, SUM(i.Total) sales
    FROM Invoice i
    {where_sql}
    GROUP BY period ORDER BY period ASC
    """
    df = pd.read_sql(query, conn, params=params)
    conn.close()
    return jsonify({'trend': df.to_dict(orient='records')})

def generate_full_trend(config):
    conn = get_db_connection()
    if not conn:
        return jsonify({'error':'数据库连接失败'}), 500
    gran = config.get('time_granularity', 'month')
    groupby, label_fmt = get_timegroup(gran)

    where_sql, params = build_where_clause(config)
    query = f"""
    SELECT {groupby} period, COUNT(i.InvoiceId) orders, SUM(i.Total) sales
    FROM Invoice i
    {where_sql}
    GROUP BY period ORDER BY period ASC
    """
    df = pd.read_sql(query, conn, params=params)
    conn.close()

    fig, ax = plt.subplots(figsize=(12,6))
    ax.plot(df['period'], df['sales'], marker='o', label='销售额')
    ax.set_ylabel('销售额($)')
    ax.set_xlabel('时间')
    ax2 = ax.twinx()
    ax2.plot(df['period'], df['orders'], marker='^', color='orange', label='订单数')
    ax2.set_ylabel('订单数')
    plt.title(f'{gran}趋势分析')
    plt.xticks(rotation=45)
    plt.tight_layout()
    chart = fig_to_base64(fig)
    return jsonify({'chart': chart, 'data': df.to_dict(orient='records')})

def get_timegroup(gran):
    if gran == 'day':
        return "DATE(i.InvoiceDate)", "%Y-%m-%d"
    elif gran == 'week':
        return "YEARWEEK(i.InvoiceDate)", "W%U"
    elif gran == 'month':
        return "DATE_FORMAT(i.InvoiceDate, '%Y-%m')", "%Y-%m"
    elif gran == 'quarter':
        return "CONCAT(YEAR(i.InvoiceDate),'-Q',QUARTER(i.InvoiceDate))", "%Y-Q%q"
    elif gran == 'year':
        return "YEAR(i.InvoiceDate)", "%Y"
    return "DATE(i.InvoiceDate)", "%Y-%m-%d"