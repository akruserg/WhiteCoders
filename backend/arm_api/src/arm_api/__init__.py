import logging
import uuid

from flask import Flask, g, jsonify, request

from .core.config import Config
from .core.errors import register_error_handlers
from .core.extensions import db, migrate
from .core.logging import setup_logging
from .core.xmlapi import XmlAwareRequest, convert_response, validate_xml_body
from .routes import register_routes


def create_app(config_object=Config):
    app = Flask(__name__)
    app.request_class = XmlAwareRequest  # тело запроса можно слать в XML
    app.config.from_object(config_object)
    app.json.ensure_ascii = False
    app.json.sort_keys = False
    app.url_map.strict_slashes = False

    setup_logging(app.config["LOG_FORMAT"], app.config["LOG_LEVEL"])

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


def _outage_response(exc):
    """БД недоступна: ответ обучающегося уходит в буфер, остальное - 503."""
    from .core.errors import error_response
    from .services import spool

    app_logger = logging.getLogger("arm_api")
    app_logger.warning("БД недоступна: %s", str(exc)[:200])
    body, status_code, headers = spool.outage_response(request)
    if status_code == 202:
        response = jsonify(body)
        response.status_code = 202
    else:
        response, _ = error_response(body["message"], status_code, code=body["code"])
        response.status_code = status_code
    response.headers.update(headers)
    return response


def _register_request_hooks(app):
    origins = app.config["CORS_ORIGINS"]

    @app.before_request
    def _assign_request_id():
        g.request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex
        if request.method == "OPTIONS":
            return ("", 204)

    @app.before_request
    def _reject_broken_xml():
        return validate_xml_body()

    @app.before_request
    def _require_authentication():
        from .core.security import authenticate_protected_request
        from .services.spool import is_db_outage

        try:
            authenticate_protected_request()
        except Exception as exc:
            if not is_db_outage(exc):
                raise
            return _outage_response(exc)  # БД недоступна: буфер или 503

    @app.after_request
    def _finalize(response):
        response = convert_response(response)  # XML-ответ по Accept или ?format=xml
        response.headers["X-Request-Id"] = getattr(g, "request_id", "")
        _add_cors(response, origins)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response


def _add_cors(response, origins):
    origin = request.headers.get("Origin")
    if not (origin and ("*" in origins or origin in origins)):
        return
    response.headers["Access-Control-Allow-Origin"] = origin
    response.vary.add("Origin")
    if origin in origins:  # учетные данные - только явно разрешенным
        response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["Access-Control-Allow-Headers"] = (
        "Authorization, Content-Type, Accept, X-Request-Id"
    )
    response.headers["Access-Control-Allow-Methods"] = (
        "GET, POST, PATCH, PUT, DELETE, OPTIONS"
    )
    response.headers["Access-Control-Expose-Headers"] = "Retry-After, X-Request-Id"
    response.headers["Access-Control-Max-Age"] = "600"


app = create_app()
