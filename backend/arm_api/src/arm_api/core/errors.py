"""* Любая ошибка отдается одинаково:
{
  "error": {"code": "not_found", "message": "...", "details": {...}},
  "request_id": "..."
}
"""

from flask import g, jsonify
from werkzeug.exceptions import HTTPException

_DEFAULT_CODES = {
    400: "bad_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    422: "validation_error",
    429: "too_many_requests",
    500: "internal_error",
    503: "service_unavailable",
}


class ApiError(Exception):
    def __init__(self, message, status=400, code=None, details=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code or _DEFAULT_CODES.get(status, "error")
        self.details = details or {}

    def to_dict(self):
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            },
            "request_id": getattr(g, "request_id", None),
        }


def error_response(message, status=400, code=None, details=None):
    err = ApiError(message, status=status, code=code, details=details)
    return jsonify(err.to_dict()), status


def register_error_handlers(app, db):
    @app.errorhandler(ApiError)
    def _api_error(exc):
        db.session.rollback()
        return jsonify(exc.to_dict()), exc.status

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        db.session.rollback()
        return error_response(
            exc.description or exc.name,
            status=exc.code or 500,
            code=_DEFAULT_CODES.get(exc.code, "error"),
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):
        db.session.rollback()
        app.logger.exception("Необработанная ошибка: %s", exc)
        return error_response("Внутренняя ошибка сервиса", status=500)
