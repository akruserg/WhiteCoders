"""
GET /me/progress            - собственный прогресс и история ошибок
GET /me/attempts            - свои карточки с оценками
GET /me/recommendations     - рекомендации системы по улучшению навыков
GET /users/{id}/progress    - прогресс конкретного обучающегося
GET /sessions/{id}/results  - результаты занятия по обучающимся
GET /analytics/heatmap      - тепловая карта ошибок
GET /analytics/overview     - сводка по системе
"""

from flask import Blueprint, request
from sqlalchemy import select

from ..core.errors import ApiError
from ..core.extensions import db
from ..core.pagination import paginate
from ..core.security import current_user, is_admin, is_student, require
from ..models import Attempt, AttemptStatus, Insight, TrainingSession, User
from ..services import analytics
from ._helpers import get_or_404, ok

results_bp = Blueprint("results", __name__)


@results_bp.get("/me/progress")
def my_progress():
    principal = current_user()
    session_id = request.args.get("session_id")
    return ok(analytics.user_progress(principal.id, session_id))


@results_bp.get("/me/attempts")
def my_attempts():
    principal = current_user()
    stmt = (
        select(Attempt)
        .where(
            Attempt.user_id == principal.id, Attempt.status == AttemptStatus.EVALUATED
        )
        .order_by(Attempt.submitted_at.desc())
    )
    if request.args.get("session_id"):
        stmt = stmt.where(Attempt.session_id == request.args["session_id"])
    return ok(
        paginate(
            stmt,
            serializer=lambda a: {
                "attempt_id": str(a.id),
                "session_id": str(a.session_id),
                "seq": a.seq,
                "score": a.final_score,
                "passed": a.passed,
                "duration_ms": a.duration_ms,
                "time_limit_sec": a.time_limit_sec,
                "delta_sec": round((a.time_overrun_ms or 0) / 1000, 1),
                "errors_count": len(a.errors),
                "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
            },
        )
    )


@results_bp.get("/me/recommendations")
def my_recommendations():
    principal = current_user()
    rows = list(
        db.session.execute(
            select(Insight)
            .where(
                Insight.target_user_id == principal.id, Insight.is_published.is_(True)
            )
            .order_by(Insight.created_at.desc())
            .limit(20)
        ).scalars()
    )
    return ok({"items": [row.to_dict() for row in rows], "total": len(rows)})


@results_bp.get("/users/<uuid:user_id>/progress")
def user_progress(user_id):
    principal = current_user()
    if is_student(principal) and principal.id != user_id:
        raise ApiError("Результаты других обучающихся недоступны", 403)
    if not is_student(principal):
        require("report.read.any")
    get_or_404(User, user_id, "Пользователь")
    return ok(analytics.user_progress(user_id, request.args.get("session_id")))


@results_bp.get("/sessions/<uuid:session_id>/results")
def session_results(session_id):
    principal = require("session.manage", "report.read.any")
    session = get_or_404(TrainingSession, session_id, "Занятие")
    if not is_admin(principal) and session.teacher_id != principal.id:
        raise ApiError("Занятие другого преподавателя", 403)
    data = analytics.session_results(session.id)
    data["session"] = session.to_dict()
    return ok(data)


@results_bp.get("/analytics/heatmap")
def heatmap():
    require("report.read.any", "insight.manage")
    return ok(
        analytics.error_heatmap(
            session_id=request.args.get("session_id"),
            group_id=request.args.get("group_id"),
            category_id=request.args.get("category_id", type=int),
        )
    )


@results_bp.get("/analytics/overview")
def overview():
    require("report.read.any", "system.monitor")
    return ok(analytics.system_usage())
