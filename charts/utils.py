import mysql.connector
from mysql.connector import Error
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import io
import base64
import logging
import platform
from functools import lru_cache
from config import DB_CONFIG


# ========== 中文字体配置 ==========
def _setup_chinese_font():
    """根据操作系统自动配置中文字体"""
    system = platform.system()

    if system == 'Windows':
        # Windows 优先使用微软雅黑，备选黑体
        plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'SimSun']
    elif system == 'Darwin':  # macOS
        plt.rcParams['font.sans-serif'] = ['PingFang SC', 'Heiti SC', 'Arial Unicode MS']
    else:  # Linux
        plt.rcParams['font.sans-serif'] = ['WenQuanYi Micro Hei', 'Noto Sans CJK SC', 'DejaVu Sans']

    # 解决负号显示为方框的问题
    plt.rcParams['axes.unicode_minus'] = False

    # 设置全局字体大小
    plt.rcParams['font.size'] = 11


# 立即执行字体配置
_setup_chinese_font()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_connection_pool = None


def get_db_connection():
    global _connection_pool
    max_retries = 3
    retry_count = 0
    while retry_count < max_retries:
        try:
            if _connection_pool is None:
                from mysql.connector.pooling import MySQLConnectionPool
                _connection_pool = MySQLConnectionPool(
                    pool_name="mypool",
                    pool_size=5,
                    **DB_CONFIG
                )
            conn = _connection_pool.get_connection()
            return conn
        except Error as e:
            retry_count += 1
            logger.error(f"数据库连接失败 (尝试 {retry_count}/{max_retries}): {e}")
            if retry_count == max_retries:
                return None


def fig_to_base64(fig, dpi=150, format='png'):  # 默认 DPI 从 100 提高到 150
    try:
        buf = io.BytesIO()
        fig.savefig(buf, format=format, dpi=dpi, bbox_inches='tight',
                    facecolor='white', edgecolor='none')
        buf.seek(0)
        img_str = base64.b64encode(buf.read()).decode('utf-8')
        plt.close(fig)
        return img_str
    except Exception as e:
        logger.error(f"图形转换失败: {e}")
        plt.close(fig)
        return None


def build_where_clause(config, alias_dict=None):
    conditions = []
    params = []
    alias = alias_dict if alias_dict else {}

    date_col = alias.get('invoice_date', 'i.InvoiceDate')
    if config.get('start_date') and config.get('end_date'):
        conditions.append(f"{date_col} BETWEEN %s AND %s")
        params.extend([config['start_date'], config['end_date']])

    if config.get('genres'):
        placeholders = ', '.join(['%s'] * len(config['genres']))
        conditions.append(f"g.Name IN ({placeholders})")
        params.extend(config['genres'])

    if config.get('countries'):
        placeholders = ', '.join(['%s'] * len(config['countries']))
        conditions.append(f"c.Country IN ({placeholders})")
        params.extend(config['countries'])

    if config.get('cities'):
        placeholders = ', '.join(['%s'] * len(config['cities']))
        conditions.append(f"c.City IN ({placeholders})")
        params.extend(config['cities'])

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
    return where_clause, params


@lru_cache(maxsize=128)
def get_cached_data(query, params=None):
    conn = get_db_connection()
    if not conn:
        return None
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(query, params or ())
        result = cursor.fetchall()
        return result
    except Error as e:
        logger.error(f"查询失败: {e}")
        return None
    finally:
        conn.close()