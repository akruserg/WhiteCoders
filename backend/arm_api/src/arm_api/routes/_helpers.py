import uuid

from flask import jsonify, request

from ..core.errors import ApiError
from ..core.extensions import db
from ..schemas import ValidationError


def body(schema_cls):
    try:
        return schema_cls.from_request()
    except ValidationError as exc:
        raise ApiError(
            "Ошибка валидации данных", 422, code="validation_error", details=exc.errors
        )


def query(schema_cls):
    try:
        return schema_cls.from_query()
    except ValidationError as exc:
        raise ApiError(
            "Ошибка валидации параметров",
            422,
            code="validation_error",
            details=exc.errors,
        )


def get_or_404(model, ident, name="Объект", lock=False):
    """lock=True блокирует строку до конца транзакции (SELECT ... FOR UPDATE)."""
    obj = db.session.get(model, ident, with_for_update=lock)
    if obj is None:
        raise ApiError(f"{name} не найден", 404)
    return obj


def ok(payload, status=200):
    return jsonify(payload), status


def item(model, status=200):
    return jsonify(model.to_dict()), status


def items(rows):
    return jsonify({"items": [row.to_dict() for row in rows], "total": len(rows)})


def commit():
    db.session.commit()


def apply_patch(instance, payload, fields):
    changed = {}
    for name in fields:
        value = getattr(payload, name, None)
        if value is None:
            continue
        setattr(instance, name, value)
        changed[name] = value if not hasattr(value, "value") else value.value
    return changed


def uuid_arg(name):
    """UUID из query-параметра; мусорное значение - 422, а не ошибка БД (500)."""
    raw = request.args.get(name)
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise ApiError(
            f"Параметр {name} должен быть UUID", 422, code="validation_error"
        )


def int_arg(name):
    raw = request.args.get(name)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise ApiError(
            f"Параметр {name} должен быть целым числом", 422, code="validation_error"
        )


def provided_fields():
    """Имена полей, которые клиент действительно прислал (для PATCH)."""
    data = request.get_json(silent=True)
    return set(data) if isinstance(data, dict) else set()
