import aiomysql
from config import DB_CONFIG

pool = None

async def init_pool():
    global pool
    if pool is None:
        pool = await aiomysql.create_pool(
            host=DB_CONFIG["host"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            db=DB_CONFIG["database"],
            charset=DB_CONFIG["charset"],
            autocommit=True,
            minsize=1,
            maxsize=10
        )
    return pool