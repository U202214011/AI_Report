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

    fig, ax = plt.subplots(figsize=(12, 6), dpi=150)

    # 设置图表样式
    plt.style.use('seaborn-v0_8-whitegrid')

    # 销售额折线图
    sales_line, = ax.plot(df['period'], df['sales'], marker='o', markersize=8, linewidth=3, color='#2563eb',
                          label='销售额', alpha=0.8)

    # 设置坐标轴
    ax.set_ylabel('销售额 ($)', fontsize=12, fontweight='bold', color='#2563eb')
    ax.set_xlabel('时间', fontsize=12, fontweight='bold')

    # 添加网格
    ax.grid(True, linestyle='--', alpha=0.7)

    # 订单数折线图
    ax2 = ax.twinx()
    orders_line, = ax2.plot(df['period'], df['orders'], marker='^', markersize=8, linewidth=3, color='#dc2626',
                            label='订单数', alpha=0.8)
    ax2.set_ylabel('订单数', fontsize=12, fontweight='bold', color='#dc2626')

    # 设置标题
    plt.title(f'{gran}趋势分析', fontsize=14, fontweight='bold', pad=20)

    # 设置图例
    ax.legend(handles=[sales_line, orders_line], loc='upper left', fontsize=10, frameon=True, shadow=True)

    # 设置坐标轴样式
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax2.spines['top'].set_visible(False)
    ax2.spines['left'].set_visible(False)

    # 设置刻度
    plt.xticks(rotation=45, ha='right', fontsize=10)
    ax.tick_params(axis='y', colors='#2563eb')
    ax2.tick_params(axis='y', colors='#dc2626')

    # 添加数据标签
    for i, (sales, orders) in enumerate(zip(df['sales'], df['orders'])):
        ax.annotate(f'${sales:.2f}',
                    xy=(df['period'][i], sales),
                    xytext=(0, 10),
                    textcoords='offset points',
                    ha='center', va='bottom',
                    fontsize=8, color='#2563eb',
                    bbox=dict(boxstyle='round,pad=0.3', fc='white', ec='none', alpha=0.7))

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