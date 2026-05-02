from flask import Flask
from routes import register_routes
import os
from models.db_init import ensure_indexes


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config['DATABASE_URL'] = os.getenv(
        'DATABASE_URL',
        'mysql+pymysql://user:password@localhost:3306/chinook'
        #'mysql+pymysql://user:password@localhost:13318/chinook'
    )

    # 添加这行解决中文乱码
    try:
        app.json.ensure_ascii = False  # Flask 2.3.0+
    except AttributeError:
        app.config['JSON_AS_ASCII'] = False  # 旧版本

    # 应用启动时执行索引自检（幂等，不阻断启动）
    ensure_indexes()

    register_routes(app)
    return app

if __name__ == "__main__":
    app = create_app()
    debug_mode = os.getenv('FLASK_DEBUG', 'false').strip().lower() in ('1', 'true', 'yes', 'on')
    app.run(debug=debug_mode, host="0.0.0.0", port=int(os.getenv('PORT', 5000)))
