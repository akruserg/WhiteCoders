"""
GET /             - проверка живости (без авторизации)
GET /openapi.json - спецификация OpenAPI 3.1 для фронтенда
"""

from flask import Blueprint, current_app, jsonify

meta_bp = Blueprint("meta", __name__)

_CONVERTERS = {
    "int": {"type": "integer"},
    "uuid": {"type": "string", "format": "uuid"},
    "path": {"type": "string"},
    "string": {"type": "string"},
    "default": {"type": "string"},
}

_TAGS = {
    "auth": "Аутентификация",
    "users": "Пользователи и группы",
    "catalog": "Справочники",
    "scenarios": "Учебные сценарии",
    "materials": "Методические материалы",
    "sessions": "Занятия и карточки",
    "results": "Прогресс и аналитика",
    "reports": "Отчеты, инсайты, сертификаты",
    "system": "Администрирование",
    "meta": "Служебные",
}


@meta_bp.get("/")
def index():
    return jsonify(
        {
            "service": "АРМ-112: учебное ПО подготовки операторов ДДС",
            "status": "ok",
            "api": current_app.config["API_PREFIX"],
            "openapi": current_app.config["API_PREFIX"] + "/openapi.json",
        }
    )


def build_openapi(app):
    prefix = app.config["API_PREFIX"]
    paths = {}

    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        blueprint = rule.endpoint.split(".")[0]
        view = app.view_functions[rule.endpoint]
        doc = (view.__doc__ or "").strip().splitlines()
        summary = doc[0] if doc else rule.endpoint

        path = rule.rule
        parameters = []
        for argument in sorted(rule.arguments):
            converter = "default"
            for candidate in ("uuid", "int", "path", "string"):
                if f"<{candidate}:{argument}>" in path:
                    converter = candidate
                    path = path.replace(f"<{candidate}:{argument}>", f"{{{argument}}}")
            path = path.replace(f"<{argument}>", f"{{{argument}}}")
            parameters.append(
                {
                    "name": argument,
                    "in": "path",
                    "required": True,
                    "schema": _CONVERTERS[converter],
                }
            )

        entry = paths.setdefault(path, {})
        for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            operation = {
                "operationId": f"{rule.endpoint}_{method.lower()}",
                "tags": [_TAGS.get(blueprint, blueprint)],
                "summary": summary,
                "parameters": parameters,
                "responses": {
                    "200": {"description": "Успешный ответ"},
                    "401": {"$ref": "#/components/responses/Unauthorized"},
                    "403": {"$ref": "#/components/responses/Forbidden"},
                    "404": {"$ref": "#/components/responses/NotFound"},
                    "422": {"$ref": "#/components/responses/ValidationError"},
                },
            }
            if method in {"POST", "PUT", "PATCH"}:
                operation["requestBody"] = {
                    "content": {"application/json": {"schema": {"type": "object"}}}
                }
            if path in {
                "/",
                f"{prefix}/auth/login",
                f"{prefix}/auth/mfa",
                f"{prefix}/auth/refresh",
                f"{prefix}/auth/logout",
                f"{prefix}/openapi.json",
            }:
                operation["security"] = []
            entry[method.lower()] = operation

    error_schema = {
        "type": "object",
        "properties": {
            "error": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "message": {"type": "string"},
                    "details": {"type": "object"},
                },
            },
            "request_id": {"type": "string"},
        },
    }

    def response(description):
        return {
            "description": description,
            "content": {
                "application/json": {"schema": {"$ref": "#/components/schemas/Error"}}
            },
        }

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "АРМ-112. API учебного ПО подготовки операторов ДДС",
            "version": "1.0.0",
            "description": (
                "REST API (JSON) учебного комплекса. Работает в изолированном "
                "контуре, авторизация — Bearer JWT, разграничение доступа — RBAC."
            ),
        },
        "servers": [{"url": "/", "description": "Локальный учебный комплекс"}],
        "security": [{"bearerAuth": []}],
        "components": {
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "JWT",
                }
            },
            "schemas": {
                "Error": error_schema,
                "Page": {
                    "type": "object",
                    "properties": {
                        "items": {"type": "array", "items": {"type": "object"}},
                        "page": {"type": "integer"},
                        "per_page": {"type": "integer"},
                        "total": {"type": "integer"},
                        "pages": {"type": "integer"},
                    },
                },
                "TokenPair": {
                    "type": "object",
                    "properties": {
                        "access_token": {"type": "string"},
                        "token_type": {"type": "string", "example": "Bearer"},
                        "expires_in": {"type": "integer"},
                        "refresh_token": {"type": "string"},
                        "user": {"type": "object"},
                    },
                },
            },
            "responses": {
                "Unauthorized": response("Требуется авторизация"),
                "Forbidden": response("Недостаточно прав"),
                "NotFound": response("Объект не найден"),
                "ValidationError": response("Ошибка валидации данных"),
            },
        },
        "paths": paths,
    }


@meta_bp.get("/openapi.json")
def openapi():
    return jsonify(build_openapi(current_app))
