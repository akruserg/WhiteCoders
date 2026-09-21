"""Режим аттестации (ТЗ: аттестационные мероприятия).

Занятие становится аттестацией, если при создании передан объект attestation:

    {"pass_score": 75, "min_attempts": 3, "certificate": true, "valid_months": 12}

Что меняется по сравнению с обычным занятием:
  - проходной балл фиксирован в занятии и не зависит от профиля оценивания;
  - пока занятие идет, обучающийся видит только балл и зачет карточки, без разбора
    ошибок и эталонных значений (иначе ответы можно передать другим участникам);
  - при завершении занятия итог считается по всем участникам: средний балл и число
    карточек; успешно прошедшим автоматически выдается сертификат;
  - результат сохраняется в занятии (протокол аттестации) и входит в отчет о занятии.
"""

from sqlalchemy import func, select

from ..core.extensions import db
from ..models import (
    Attempt,
    AttemptStatus,
    Certificate,
    SessionParticipant,
    SessionStatus,
    User,
)
from . import certificates

DEFAULTS = {
    "pass_score": None,  # None - берется DEFAULT_PASS_SCORE из настроек
    "min_attempts": 1,
    "certificate": True,
    "valid_months": 12,
}
_EVALUATED = (AttemptStatus.SUBMITTED, AttemptStatus.EVALUATED)
# что видит обучающийся в результате карточки, пока аттестация идет
_VISIBLE = (
    "attempt_id",
    "session_id",
    "seq",
    "status",
    "score",
    "passed",
    "duration_ms",
    "time_limit_sec",
    "delta_sec",
)


def normalize(raw, default_pass_score):
    """Проверка параметров аттестации. Возвращает словарь настроек или список ошибок."""
    if not isinstance(raw, dict):
        return None, ["attestation: ожидается объект"]
    unknown = sorted(set(raw) - set(DEFAULTS))
    errors = [f"attestation.{k}: неизвестный параметр" for k in unknown]
    cfg = {**DEFAULTS, **{k: v for k, v in raw.items() if k in DEFAULTS}}
    if cfg["pass_score"] is None:
        cfg["pass_score"] = float(default_pass_score)
    score = cfg["pass_score"]
    if (
        isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not 1 <= score <= 100
    ):
        errors.append("attestation.pass_score: число от 1 до 100")
    attempts = cfg["min_attempts"]
    if (
        isinstance(attempts, bool)
        or not isinstance(attempts, int)
        or not 1 <= attempts <= 100
    ):
        errors.append("attestation.min_attempts: целое от 1 до 100")
    if not isinstance(cfg["certificate"], bool):
        errors.append("attestation.certificate: true или false")
    months = cfg["valid_months"]
    if (
        isinstance(months, bool)
        or not isinstance(months, int)
        or not 1 <= months <= 120
    ):
        errors.append("attestation.valid_months: целое от 1 до 120")
    if errors:
        return None, errors
    cfg["pass_score"] = float(cfg["pass_score"])
    return cfg, []


def config(session):
    return (session.settings or {}).get("attestation")


def decide(scores, pass_score, min_attempts):
    """Итог по одному обучающемуся: средний балл, число карточек, аттестован ли."""
    attempts = len(scores)
    average = round(sum(scores) / attempts, 2) if attempts else 0.0
    return {
        "average": average,
        "attempts": attempts,
        "passed": attempts >= min_attempts and average >= pass_score,
        "enough_attempts": attempts >= min_attempts,
    }


def redact(result):
    """Результат карточки для обучающегося во время аттестации: без разбора ошибок."""
    hidden = {k: v for k, v in result.items() if k in _VISIBLE}
    hidden["details_hidden"] = (
        "Разбор ошибок будет доступен после завершения аттестации"
    )
    return hidden


def is_active(session):
    return config(session) is not None and session.status is SessionStatus.RUNNING


def _scores_by_user(session_id):
    rows = db.session.execute(
        select(
            Attempt.user_id,
            func.coalesce(Attempt.expert_score, Attempt.score),
        ).where(
            Attempt.session_id == session_id,
            Attempt.status.in_(_EVALUATED),
            Attempt.score.is_not(None),
        )
    ).all()
    scores = {}
    for user_id, value in rows:
        scores.setdefault(user_id, []).append(float(value))
    return scores


def summarize(session):
    """Протокол: по каждому участнику итог и номер сертификата (если выдан)."""
    cfg = config(session)
    scores = _scores_by_user(session.id)
    participants = db.session.execute(
        select(User.id, User.full_name)
        .join(SessionParticipant, SessionParticipant.user_id == User.id)
        .where(SessionParticipant.session_id == session.id)
        .order_by(User.full_name)
    ).all()
    numbers = dict(
        db.session.execute(
            select(Certificate.user_id, Certificate.number).where(
                Certificate.session_id == session.id
            )
        ).all()
    )
    students = []
    for user_id, full_name in participants:
        item = decide(scores.get(user_id, []), cfg["pass_score"], cfg["min_attempts"])
        students.append(
            {
                "user_id": str(user_id),
                "full_name": full_name,
                **item,
                "certificate": numbers.get(user_id),
            }
        )
    return {
        "config": cfg,
        "students": students,
        "passed": sum(1 for s in students if s["passed"]),
        "total": len(students),
    }


def finalize(session, issued_by_id):
    """Вызывается при завершении занятия: выдает сертификаты и сохраняет протокол."""
    cfg = config(session)
    if cfg is None:
        return None
    report = summarize(session)
    if cfg["certificate"]:
        for student in report["students"]:
            if student["passed"] and not student["certificate"]:
                user = db.session.get(User, student["user_id"])
                cert = certificates.issue(
                    user, session.id, issued_by_id, cfg["valid_months"]
                )
                student["certificate"] = cert.number
    session.settings = {
        **(session.settings or {}),
        "attestation_result": {
            "finished_at": session.finished_at.isoformat(),
            "students": report["students"],
        },
    }
    return report
