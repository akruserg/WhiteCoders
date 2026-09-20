from flask import current_app, request
from sqlalchemy import func, select

from .errors import ApiError
from .extensions import db


def page_params():
    cfg = current_app.config
    try:
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", cfg["DEFAULT_PAGE_SIZE"]))
    except ValueError:
        raise ApiError("page и per_page должны быть целыми числами", 422)
    if page < 1 or per_page < 1:
        raise ApiError("page и per_page должны быть положительными", 422)
    return page, min(per_page, cfg["MAX_PAGE_SIZE"])


def paginate(stmt, serializer=None, page=None, per_page=None):
    if page is None or per_page is None:
        page, per_page = page_params()

    total = db.session.execute(
        select(func.count()).select_from(stmt.order_by(None).subquery())
    ).scalar_one()

    rows = list(
        db.session.execute(stmt.limit(per_page).offset((page - 1) * per_page)).scalars()
    )
    serializer = serializer or (lambda row: row.to_dict())
    return {
        "items": [serializer(row) for row in rows],
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": (total + per_page - 1) // per_page if per_page else 0,
    }
