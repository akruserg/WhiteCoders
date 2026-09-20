from sqlalchemy import Float, and_, cast, func, select

from ..core.extensions import db
from ..models import (
    Attempt,
    AttemptError,
    AttemptStatus,
    IncidentCategory,
    Scenario,
    SessionParticipant,
    SessionStatus,
    TrainingSession,
    User,
)

_EVALUATED = (AttemptStatus.SUBMITTED, AttemptStatus.EVALUATED)


def _round(value, digits=2):
    return round(float(value), digits) if value is not None else None


def attempt_stats(where):
    row = db.session.execute(
        select(
            func.count(Attempt.id),
            func.avg(cast(func.coalesce(Attempt.expert_score, Attempt.score), Float)),
            func.sum(func.cast(Attempt.passed, db.Integer)),
            func.avg(Attempt.duration_ms),
            func.sum(
                func.cast(
                    Attempt.duration_ms > Attempt.time_limit_sec * 1000, db.Integer
                )
            ),
        ).where(and_(*where))
    ).one()

    attempts, avg_score, passed, avg_duration, overruns = row
    attempts = attempts or 0
    return {
        "attempts": attempts,
        "avg_score": _round(avg_score) or 0.0,
        "passed": int(passed or 0),
        "pass_rate": _round(100.0 * (passed or 0) / attempts, 1) if attempts else 0.0,
        "avg_duration_sec": _round((avg_duration or 0) / 1000, 1),
        "time_overruns": int(overruns or 0),
    }


def error_breakdown(where, limit_fields=10):
    by_kind = db.session.execute(
        select(AttemptError.kind, func.count(AttemptError.id))
        .join(Attempt, Attempt.id == AttemptError.attempt_id)
        .where(and_(*where))
        .group_by(AttemptError.kind)
    ).all()

    by_field = db.session.execute(
        select(AttemptError.field_key, func.count(AttemptError.id))
        .join(Attempt, Attempt.id == AttemptError.attempt_id)
        .where(and_(*where), AttemptError.field_key.isnot(None))
        .group_by(AttemptError.field_key)
        .order_by(func.count(AttemptError.id).desc())
        .limit(limit_fields)
    ).all()

    return {
        "by_kind": {kind.value: count for kind, count in by_kind},
        "by_field": [{"field_key": key, "count": count} for key, count in by_field],
        "total": sum(count for _, count in by_kind),
    }


def user_progress(user_id, session_id=None):
    where = [Attempt.user_id == user_id, Attempt.status.in_(_EVALUATED)]
    if session_id:
        where.append(Attempt.session_id == session_id)

    stats = attempt_stats(where)
    errors = error_breakdown(where)

    timeline = db.session.execute(
        select(
            TrainingSession.id,
            TrainingSession.title,
            TrainingSession.started_at,
            func.count(Attempt.id),
            func.avg(cast(func.coalesce(Attempt.expert_score, Attempt.score), Float)),
        )
        .join(Attempt, Attempt.session_id == TrainingSession.id)
        .where(and_(*where))
        .group_by(TrainingSession.id, TrainingSession.title, TrainingSession.started_at)
        .order_by(TrainingSession.started_at)
        .limit(200)
    ).all()

    by_category = db.session.execute(
        select(
            IncidentCategory.code,
            IncidentCategory.name,
            func.count(Attempt.id),
            func.avg(cast(func.coalesce(Attempt.expert_score, Attempt.score), Float)),
        )
        .join(Scenario, Scenario.id == Attempt.scenario_id)
        .join(IncidentCategory, IncidentCategory.id == Scenario.category_id)
        .where(and_(*where))
        .group_by(IncidentCategory.code, IncidentCategory.name)
        .order_by(func.count(Attempt.id).desc())
    ).all()

    return {
        "user_id": str(user_id),
        "summary": stats,
        "errors": errors,
        "timeline": [
            {
                "session_id": str(sid),
                "title": title,
                "started_at": started.isoformat() if started else None,
                "attempts": count,
                "avg_score": _round(avg) or 0.0,
            }
            for sid, title, started, count, avg in timeline
        ],
        "by_category": [
            {
                "code": code,
                "name": name,
                "attempts": count,
                "avg_score": _round(avg) or 0.0,
            }
            for code, name, count, avg in by_category
        ],
    }


def session_results(session_id):
    rows = db.session.execute(
        select(
            User.id,
            User.full_name,
            func.count(Attempt.id),
            func.avg(cast(func.coalesce(Attempt.expert_score, Attempt.score), Float)),
            func.sum(func.cast(Attempt.passed, db.Integer)),
            func.avg(Attempt.duration_ms),
            func.sum(
                func.cast(
                    Attempt.duration_ms > Attempt.time_limit_sec * 1000, db.Integer
                )
            ),
        )
        .join(SessionParticipant, SessionParticipant.user_id == User.id)
        .outerjoin(
            Attempt,
            and_(Attempt.user_id == User.id, Attempt.session_id == session_id),
        )
        .where(SessionParticipant.session_id == session_id)
        .group_by(User.id, User.full_name)
        .order_by(User.full_name)
    ).all()

    where = [Attempt.session_id == session_id]
    return {
        "session_id": str(session_id),
        "summary": attempt_stats(where + [Attempt.status.in_(_EVALUATED)]),
        "errors": error_breakdown(where),
        "students": [
            {
                "user_id": str(uid),
                "full_name": name,
                "attempts": attempts or 0,
                "avg_score": _round(avg) or 0.0,
                "passed": int(passed or 0),
                "avg_duration_sec": _round((avg_duration or 0) / 1000, 1),
                "time_overruns": int(overruns or 0),
            }
            for uid, name, attempts, avg, passed, avg_duration, overruns in rows
        ],
    }


def error_heatmap(session_id=None, group_id=None, category_id=None):
    where = [Attempt.status.in_(_EVALUATED)]
    stmt = select(
        func.coalesce(AttemptError.field_key, "-"),
        AttemptError.kind,
        func.count(AttemptError.id),
    ).join(Attempt, Attempt.id == AttemptError.attempt_id)
    if session_id:
        where.append(Attempt.session_id == session_id)
    if category_id:
        stmt = stmt.join(Scenario, Scenario.id == Attempt.scenario_id)
        where.append(Scenario.category_id == category_id)
    if group_id:
        stmt = stmt.join(TrainingSession, TrainingSession.id == Attempt.session_id)
        where.append(TrainingSession.group_id == group_id)

    rows = db.session.execute(
        stmt.where(and_(*where))
        .group_by(AttemptError.field_key, AttemptError.kind)
        .order_by(func.count(AttemptError.id).desc())
        .limit(500)
    ).all()

    fields, kinds, cells = [], [], []
    for field_key, kind, count in rows:
        if field_key not in fields:
            fields.append(field_key)
        if kind.value not in kinds:
            kinds.append(kind.value)
        cells.append({"field_key": field_key, "kind": kind.value, "count": count})
    return {"fields": fields, "kinds": kinds, "cells": cells}


def system_usage():
    users_total = db.session.execute(select(func.count(User.id))).scalar_one()
    users_active = db.session.execute(
        select(func.count(User.id)).where(
            User.is_active.is_(True), User.is_blocked.is_(False)
        )
    ).scalar_one()
    sessions_total = db.session.execute(
        select(func.count(TrainingSession.id))
    ).scalar_one()
    sessions_running = db.session.execute(
        select(func.count(TrainingSession.id)).where(
            TrainingSession.status == SessionStatus.RUNNING
        )
    ).scalar_one()
    attempts = attempt_stats([Attempt.status.in_(_EVALUATED)])
    return {
        "users_total": users_total,
        "users_active": users_active,
        "sessions_total": sessions_total,
        "sessions_running": sessions_running,
        "attempts": attempts,
    }
