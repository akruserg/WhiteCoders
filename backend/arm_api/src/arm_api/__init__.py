import logging
import uuid

from flask import Flask, g, jsonify, request

from .core.config import Config
from .core.errors import register_error_handlers
from .core.extensions import db, migrate
from .routes import register_routes


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)
    app.json.ensure_ascii = False
    app.json.sort_keys = False
    app.url_map.strict_slashes = False

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    db.init_app(app)
    migrate.init_app(app, db)

    from . import models  # noqa: F401  (регистрирует модели в SQLAlchemy)

    register_routes(app)
    register_error_handlers(app, db)
    _register_request_hooks(app)

    @app.get("/")
    def index():
        return jsonify(
            {
                "service": "АРМ-112: учебное ПО подготовки операторов ДДС",
                "status": "ok",
                "api": app.config["API_PREFIX"],
                "openapi": app.config["API_PREFIX"] + "/openapi.json",
            }
        )

    return app


def _register_request_hooks(app):
    origins = app.config["CORS_ORIGINS"]

    @app.before_request
    def _assign_request_id():
        g.request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex
        if request.method == "OPTIONS":
            return ("", 204)

    @app.before_request
    def _require_authentication():
        from .core.security import authenticate_protected_request

        authenticate_protected_request()

    @app.after_request
    def _finalize(response):
        response.headers["X-Request-Id"] = getattr(g, "request_id", "")
        origin = request.headers.get("Origin")
        if origin and ("*" in origins or origin in origins):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            if origin in origins:  # учетные данные - только явно разрешенным
                response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Headers"] = (
                "Authorization, Content-Type, X-Request-Id"
            )
            response.headers["Access-Control-Allow-Methods"] = (
                "GET, POST, PATCH, PUT, DELETE, OPTIONS"
            )
            response.headers["Access-Control-Max-Age"] = "600"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response


app = create_app()
