from flask import jsonify
import pandas as pd
import matplotlib.pyplot as plt
from .utils import get_db_connection, fig_to_base64, build_where_clause
from models.schema_config import DIMENSIONS

SUPPORTED_DIMENSIONS = [
    key for key in DIMENSIONS.keys()
    if key != "total"
]


def preview_stats(config):
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': '数据库连接失败'}), 500

    where_sql, params = build_where_clause(config)
    query = f"""
    SELECT 
        COUNT(DISTINCT i.InvoiceId) total_orders,
        SUM(i.Total) total_sales,
        SUM(i.Total)/COUNT(DISTINCT i.InvoiceId) avg_order_value
    FROM Invoice i
    JOIN Customer c ON i.CustomerId = c.CustomerId
    {where_sql}
    """
    df = pd.read_sql(query, conn, params=params)
    conn.close()
    if df.empty:
        return jsonify({'error': '无数据'}), 200
    preview = df.iloc[0].to_dict()
    return jsonify(preview)


def generate_full_stats(config):
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': '数据库连接失败'}), 500

    dims = config.get('dimensions', {k: True for k in SUPPORTED_DIMENSIONS})

    out = {'charts': {}, 'data': {}}

    out['data']['base'] = pd.read_sql(
        "SELECT COUNT(*) total_orders, SUM(Total) total_sales, SUM(Total)/COUNT(*) avg_order_value FROM Invoice",
        conn
    ).iloc[0].to_dict()

    if dims.get('genre'):
        df = pd.read_sql("""
        SELECT g.Name AS genre, SUM(i.Total) sales
        FROM Invoice i
          JOIN InvoiceLine il ON i.InvoiceId = il.InvoiceId
          JOIN Track t ON il.TrackId = t.TrackId
          JOIN Genre g ON t.GenreId = g.GenreId
        GROUP BY g.GenreId
        ORDER BY sales DESC
        """, conn)
        if not df.empty:
            out['data']['genre'] = df.to_dict(orient='records')
            fig, ax = plt.subplots(figsize=(10, 8), dpi=150)
            import numpy as np

            # 使用更现代的颜色方案
            colors = plt.cm.tab20(np.linspace(0, 1, len(df)))
            explode = [0.05 if i < 3 else 0 for i in range(len(df))]

            # 绘制饼图
            wedges, texts, autotexts = ax.pie(
                df['sales'],
                labels=df['genre'],
                autopct='%1.1f%%',
                startangle=90,
                colors=colors,
                explode=explode,
                shadow=True,
                textprops={'fontsize': 10, 'weight': 'bold'},
                wedgeprops={'edgecolor': 'white', 'linewidth': 2}
            )

            # 设置文本样式
            for autotext in autotexts:
                autotext.set_color('white')
                autotext.set_fontsize(9)
                autotext.set_weight('bold')
                autotext.set_bbox(dict(boxstyle='round,pad=0.3', fc=(0, 0, 0, 0.5), ec='none'))

            # 设置标题
            ax.set_title('音乐类型销售占比分析', fontsize=16, pad=20, weight='bold')

            # 添加图例
            ax.legend(wedges, df['genre'], loc='center left', bbox_to_anchor=(1, 0.5), fontsize=10, frameon=True,
                      shadow=True)

            plt.tight_layout()
            out['charts']['genre_pie'] = fig_to_base64(fig, dpi=150)

    if dims.get('country'):
        df = pd.read_sql("""
        SELECT c.Country, SUM(i.Total) sales
        FROM Invoice i
        JOIN Customer c ON i.CustomerId = c.CustomerId
        GROUP BY c.Country
        ORDER BY sales DESC
        LIMIT 15
        """, conn)
        if not df.empty:
            out['data']['country'] = df.to_dict(orient='records')
            fig, ax = plt.subplots(figsize=(12, 7), dpi=150)

            # 使用更现代的颜色方案
            colors = plt.cm.tab20c(np.linspace(0.2, 0.8, len(df)))

            # 绘制柱状图
            bars = ax.bar(df['Country'], df['sales'], color=colors, edgecolor='white', linewidth=2)

            # 添加数据标签
            for bar in bars:
                height = bar.get_height()
                ax.annotate(f'${height:,.0f}',
                            xy=(bar.get_x() + bar.get_width() / 2, height),
                            xytext=(0, 8),
                            textcoords="offset points",
                            ha='center', va='bottom',
                            fontsize=9, color='navy',
                            bbox=dict(boxstyle='round,pad=0.3', fc='white', ec='none', alpha=0.7))

            # 设置坐标轴和标题
            ax.set_xlabel('国家/地区', fontsize=12, fontweight='bold')
            ax.set_ylabel('销售额 ($)', fontsize=12, fontweight='bold')
            ax.set_title('各国销售排行 Top 15', fontsize=16, pad=20, fontweight='bold')

            # 设置刻度
            plt.xticks(rotation=45, ha='right', fontsize=10)
            ax.tick_params(axis='y', labelsize=10)

            # 添加网格
            ax.yaxis.grid(True, linestyle='--', alpha=0.7)
            ax.set_axisbelow(True)

            # 设置坐标轴样式
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.spines['left'].set_visible(False)
            ax.spines['bottom'].set_color('#333333')

            # 添加渐变效果
            for bar in bars:
                height = bar.get_height()
                gradient = plt.cm.viridis(np.linspace(0, 1, 100))
                rect = bar.get_bbox()
                x = rect.x0
                y = rect.y0
                width = rect.width
                for i, color in enumerate(gradient):
                    ax.fill_between([x, x + width], [y + height * i / 100, y + height * i / 100],
                                    [y + height * (i + 1) / 100, y + height * (i + 1) / 100], color=color)

            plt.tight_layout()
            out['charts']['country_bar'] = fig_to_base64(fig, dpi=150)

    if dims.get('customer'):
        df = pd.read_sql("""
        SELECT CONCAT(c.FirstName,' ',c.LastName) customer, SUM(i.Total) sales
        FROM Invoice i
        JOIN Customer c ON i.CustomerId = c.CustomerId
        GROUP BY c.CustomerId
        ORDER BY sales DESC
        LIMIT 20
        """, conn)
        if not df.empty:
            out['data']['customer'] = df.to_dict(orient='records')
            fig, ax = plt.subplots(figsize=(12, 10), dpi=150)

            # 使用更现代的颜色方案
            colors = plt.cm.tab10(np.linspace(0.1, 0.9, len(df)))

            # 绘制水平柱状图
            bars = ax.barh(df['customer'], df['sales'], color=colors, edgecolor='white', linewidth=2)

            # 添加数据标签
            for i, bar in enumerate(bars):
                width = bar.get_width()
                ax.annotate(f'${width:,.0f}',
                            xy=(width, bar.get_y() + bar.get_height() / 2),
                            xytext=(8, 0),
                            textcoords="offset points",
                            ha='left', va='center',
                            fontsize=9, color='darkblue',
                            bbox=dict(boxstyle='round,pad=0.3', fc='white', ec='none', alpha=0.7))

            # 设置坐标轴和标题
            ax.set_xlabel('销售额 ($)', fontsize=12, fontweight='bold')
            ax.set_ylabel('客户', fontsize=12, fontweight='bold')
            ax.set_title('客户销售排行 Top 20', fontsize=16, pad=20, fontweight='bold')

            # 反转Y轴
            ax.invert_yaxis()

            # 添加网格
            ax.xaxis.grid(True, linestyle='--', alpha=0.7)
            ax.set_axisbelow(True)

            # 设置坐标轴样式
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.spines['bottom'].set_visible(False)
            ax.spines['left'].set_color('#333333')

            # 设置刻度
            ax.tick_params(axis='x', labelsize=10)
            ax.tick_params(axis='y', labelsize=10)

            # 添加渐变效果
            for bar in bars:
                width = bar.get_width()
                gradient = plt.cm.plasma(np.linspace(0, 1, 100))
                rect = bar.get_bbox()
                y = rect.y0
                height = rect.height
                for i, color in enumerate(gradient):
                    ax.fill_betweenx([y, y + height], [width * i / 100, width * i / 100],
                                     [width * (i + 1) / 100, width * (i + 1) / 100], color=color)

            plt.tight_layout()
            out['charts']['customer_bar'] = fig_to_base64(fig, dpi=150)

    if dims.get('employee'):
        df = pd.read_sql("""
        SELECT CONCAT(e.FirstName,' ',e.LastName) employee, SUM(i.Total) sales
        FROM Invoice i
        JOIN Customer c ON i.CustomerId = c.CustomerId
        LEFT JOIN Employee e ON c.SupportRepId = e.EmployeeId
        GROUP BY e.EmployeeId
        ORDER BY sales DESC
        """, conn)
        out['data']['employee'] = df.to_dict(orient='records')
        fig, ax = plt.subplots(figsize=(8, 5), dpi=150)

        # 使用更现代的颜色方案
        colors = plt.cm.tab20(np.linspace(0.2, 0.8, len(df)))

        # 绘制柱状图
        bars = ax.bar(df['employee'], df['sales'], color=colors, edgecolor='white', linewidth=2)

        # 添加数据标签
        for bar in bars:
            height = bar.get_height()
            ax.annotate(f'${height:,.0f}',
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 8),
                        textcoords="offset points",
                        ha='center', va='bottom',
                        fontsize=9, color='navy',
                        bbox=dict(boxstyle='round,pad=0.3', fc='white', ec='none', alpha=0.7))

        # 设置坐标轴和标题
        ax.set_xlabel('员工', fontsize=12, fontweight='bold')
        ax.set_ylabel('销售额 ($)', fontsize=12, fontweight='bold')
        ax.set_title('员工销售业绩', fontsize=14, pad=15, fontweight='bold')

        # 设置刻度
        plt.xticks(rotation=45, ha='right', fontsize=10)
        ax.tick_params(axis='y', labelsize=10)

        # 添加网格
        ax.yaxis.grid(True, linestyle='--', alpha=0.7)
        ax.set_axisbelow(True)

        # 设置坐标轴样式
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_visible(False)
        ax.spines['bottom'].set_color('#333333')

        # 添加渐变效果
        for bar in bars:
            height = bar.get_height()
            gradient = plt.cm.viridis(np.linspace(0, 1, 100))
            rect = bar.get_bbox()
            x = rect.x0
            y = rect.y0
            width = rect.width
            for i, color in enumerate(gradient):
                ax.fill_between([x, x + width], [y + height * i / 100, y + height * i / 100],
                                [y + height * (i + 1) / 100, y + height * (i + 1) / 100], color=color)

        plt.tight_layout()
        out['charts']['employee_bar'] = fig_to_base64(fig, dpi=150)

    conn.close()
    return jsonify(out)