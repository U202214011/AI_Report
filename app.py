from flask import Flask
from routes import register_routes
import os

def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config['DATABASE_URL'] = os.getenv(
        'DATABASE_URL',
        'mysql+pymysql://user:password@localhost:3306/chinook'
    )
    register_routes(app)
    return app

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, host="0.0.0.0", port=int(os.getenv('PORT', 5000)))