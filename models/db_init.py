import logging
from typing import Dict

import mysql.connector
from mysql.connector import Error

from config import DB_CONFIG

logger = logging.getLogger(__name__)

INDEX_DDL: Dict[str, str] = {
    "idx_invoice_invoice_date": "CREATE INDEX idx_invoice_invoice_date ON Invoice(InvoiceDate)",
    "idx_invoice_customer_id": "CREATE INDEX idx_invoice_customer_id ON Invoice(CustomerId)",
}


def ensure_indexes() -> bool:
    conn = None
    cursor = None
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute("SHOW INDEX FROM Invoice")
        existing = {row[2] for row in cursor.fetchall() if len(row) > 2}

        created = []
        for name, ddl in INDEX_DDL.items():
            if name in existing:
                continue
            cursor.execute(ddl)
            created.append(name)

        if created:
            conn.commit()
            logger.info("已自动创建索引: %s", ", ".join(created))
        else:
            logger.info("索引检查完成：目标索引已存在")

        return True
    except Error as exc:
        logger.warning("索引自检/创建失败，不阻断服务启动: %s", exc)
        return False
    except OSError as exc:
        logger.warning("索引自检/创建失败，不阻断服务启动: %s", exc)
        return False
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None and conn.is_connected():
            conn.close()
