from flask import Flask, jsonify

from .core.config import Config
from .core.extensions import db
from .routes import register_routes


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    register_routes(app)

    @app.get("/")
    def index():
        return jsonify({'status': 'ok'}), 200

    return app


app = create_app()
