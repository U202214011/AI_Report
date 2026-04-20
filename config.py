import os
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': int(os.getenv('DB_PORT', '3306')),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', '040823'),
    'database': os.getenv('DB_NAME', 'chinook'),
    'charset': 'utf8mb4',
    'use_unicode': True,
    'autocommit': True
}

APP_CONFIG = {
    'DEBUG': True,
    'SECRET_KEY': os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production'),
    'MAX_CONTENT_LENGTH': 16 * 1024 * 1024,
}