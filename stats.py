from flask import jsonify
import pandas as pd
import matplotlib.pyplot as plt
from .utils import get_db_connection, fig_to_base64, build_where_clause

SUPPORTED_DIMENSIONS = [
    'genre', 'country', 'city', 'artist', 'customer', 'employee'
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
        out['data']['genre'] = df.to_dict(orient='records')
        fig, ax = plt.subplots(figsize=(8,6))
        ax.pie(df['sales'], labels=df['genre'], autopct='%1.1f%%', startangle=90)
        out['charts']['genre_pie'] = fig_to_base64(fig)

    if dims.get('country'):
        df = pd.read_sql("""
        SELECT c.Country, SUM(i.Total) sales
        FROM Invoice i
        JOIN Customer c ON i.CustomerId = c.CustomerId
        GROUP BY c.Country
        ORDER BY sales DESC
        LIMIT 15
        """, conn)
        out['data']['country'] = df.to_dict(orient='records')
        fig, ax = plt.subplots(figsize=(10,6))
        ax.bar(df['Country'], df['sales'])
        plt.xticks(rotation=45)
        out['charts']['country_bar'] = fig_to_base64(fig)

    if dims.get('customer'):
        df = pd.read_sql("""
        SELECT CONCAT(c.FirstName,' ',c.LastName) customer, SUM(i.Total) sales
        FROM Invoice i
        JOIN Customer c ON i.CustomerId = c.CustomerId
        GROUP BY c.CustomerId
        ORDER BY sales DESC
        LIMIT 20
        """, conn)
        out['data']['customer'] = df.to_dict(orient='records')
        fig, ax = plt.subplots(figsize=(10,6))
        ax.barh(df['customer'], df['sales'])
        out['charts']['customer_bar'] = fig_to_base64(fig)

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
        fig, ax = plt.subplots(figsize=(8,5))
        ax.bar(df['employee'], df['sales'])
        plt.xticks(rotation=45)
        out['charts']['employee_bar'] = fig_to_base64(fig)

    conn.close()
    return jsonify(out)