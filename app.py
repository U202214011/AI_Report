from flask import Flask
from routes import register_routes
import os


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config['DATABASE_URL'] = os.getenv(
        'DATABASE_URL',
        # 'mysql+pymysql://user:password@localhost:3306/chinook'
        'mysql+pymysql://user:password@localhost:13318/chinook'
    )

    # 添加这行解决中文乱码
    try:
        app.json.ensure_ascii = False  # Flask 2.3.0+
    except AttributeError:
        app.config['JSON_AS_ASCII'] = False  # 旧版本

    register_routes(app)
    return app

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, host="0.0.0.0", port=int(os.getenv('PORT', 5000)))