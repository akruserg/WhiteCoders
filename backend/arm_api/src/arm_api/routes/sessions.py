"""
POST   /sessions                          - создать занятие
GET    /sessions                          - список занятий (по роли)
GET    /sessions/{id}                     - карточка занятия
PATCH  /sessions/{id}                     - настройка перед стартом
POST   /sessions/{id}/start               - инициация старта обучения
POST   /sessions/{id}/finish              - завершение занятия
GET    /sessions/{id}/monitor             - мониторинг в реальном времени
POST   /sessions/{id}/participants        - добавить обучающихся
DELETE /sessions/{id}/participants/{uid}  - исключить обучающегося

POST /sessions/{id}/attempts/next         - получить случайную карточку + вызов
POST /attempts/{id}/answer                - принять входящий вызов
POST /attempts/{id}/messages              - реплика оператора в диалоге
PUT  /attempts/{id}/draft                 - сохранить черновик карточки
POST /attempts/{id}/scenario              - сделать сценарий из карточки обучающегося
POST /attempts/{id}/submit                - отправить заполненную карточку
GET  /attempts/{id}                       - результат с разбором ошибок
POST /attempts/{id}/grade                 - экспертная оценка преподавателем
"""

import random
from datetime import datetime, timezone

from flask import Blueprint, current_app, request
from sqlalchemy import func, select

from ..core.errors import ApiError
from ..core.extensions import db
from ..core.pagination import paginate
from ..core.security import current_user, is_admin, is_student, require, write_audit
from ..models import (
    Attempt,
    AttemptError,
    AttemptStatus,
    Call,
    CallChannel,
    CallMessage,
    CallStatus,
    CardTemplate,
    ErrorKind,
    EvaluationSource,
    GradingProfile,
    Group,
    IncidentCategory,
    QuestionSource,
    Scenario,
    ScenarioOrigin,
    ScenarioStatus,
    SessionMode,
    SessionParticipant,
    SessionStatus,
    TrainingSession,
    User,
)
from ..schemas import (
    CallMessageIn,
    ExpertGradeIn,
    MembersIn,
    SessionCreate,
    SessionUpdate,
    SubmitIn,
)
from ..services import (
    ai,
    analytics,
    card_schema,
    grammar,
    integrations,
    scoring,
    settings,
)
from ._helpers import body, commit, get_or_404, ok, uuid_arg

sessions_bp = Blueprint("sessions", __name__)

# поля легенды, которые обучающийся до конца карточки видеть не должен:
# подсказки, правки преподавателя и будущие реплики заявителя
HIDDEN_FROM_STUDENT = ("hints", "corrections", "followups")


def _owned_session(session_id, principal):
    session = get_or_404(TrainingSession, session_id, "Занятие")
    if not is_admin(principal) and session.teacher_id != principal.id:
        raise ApiError("Занятие другого преподавателя", 403)
    return session


def _visible_session(session_id, principal):
    session = get_or_404(TrainingSession, session_id, "Занятие")
    if is_student(principal):
        if db.session.get(SessionParticipant, (session.id, principal.id)) is None:
            raise ApiError("Вы не участник этого занятия", 403)
    elif not is_admin(principal) and session.teacher_id != principal.id:
        raise ApiError("Занятие другого преподавателя", 403)
    return session


def _set_categories(session, category_ids):
    if category_ids is None:
        return
    categories = (
        list(
            db.session.execute(
                select(IncidentCategory).where(IncidentCategory.id.in_(category_ids))
            ).scalars()
        )
        if category_ids
        else []
    )
    missing = set(category_ids) - {c.id for c in categories}
    if missing:
        raise ApiError(f"Неизвестные категории: {sorted(missing)}", 422)
    session.categories = categories


def _resolve_profile(session, scenario=None):
    if session.grading_profile_id:
        return db.session.get(GradingProfile, session.grading_profile_id)
    if scenario is not None and scenario.grading_profile_id:
        return db.session.get(GradingProfile, scenario.grading_profile_id)
    return (
        db.session.execute(
            select(GradingProfile).where(GradingProfile.is_default.is_(True))
        )
        .scalars()
        .first()
    )


def _session_view(session, principal):
    data = session.to_dict()
    data["participants"] = [
        {
            "user_id": str(p.user_id),
            "full_name": p.user.full_name if p.user else None,
            "joined_at": p.joined_at.isoformat() if p.joined_at else None,
        }
        for p in session.participants
    ]
    data["channel"] = (session.settings or {}).get("channel", "text")
    return data


def _origins_for(source):
    if source is QuestionSource.GENERATED:
        return [ScenarioOrigin.AI, ScenarioOrigin.MANUAL, ScenarioOrigin.IMPORTED]
    if source is QuestionSource.STUDENT:
        return [ScenarioOrigin.STUDENT]
    return list(ScenarioOrigin)


def _pick_scenario(session, user):
    stmt = select(Scenario).where(
        Scenario.status == ScenarioStatus.VALIDATED,
        Scenario.difficulty.between(session.difficulty_min, session.difficulty_max),
        Scenario.origin.in_(_origins_for(session.question_source)),
    )

    categories = [c.id for c in session.categories]
    scope = [c.id for c in user.service_scope]
    if scope:
        categories = [c for c in categories if c in scope] or scope
    if categories:
        stmt = stmt.where(Scenario.category_id.in_(categories))

    used = set(
        db.session.execute(
            select(Attempt.scenario_id).where(
                Attempt.session_id == session.id, Attempt.user_id == user.id
            )
        ).scalars()
    )

    pool = list(db.session.execute(stmt.limit(500)).scalars())
    if session.mode is SessionMode.CARD_ACTIONS:
        # оцениваются шаги работы с карточкой, значит эталон обязан их содержать
        pool = [s for s in pool if s.reference_actions]
    if not pool:
        raise ApiError(
            "Нет утвержденных сценариев для выбранных категорий и уровня сложности",
            409,
            code="no_scenarios",
        )
    fresh = [s for s in pool if s.id not in used]
    return random.choice(fresh or pool)


@sessions_bp.post("/sessions")
def create_session():
    principal = require("session.manage")
    payload = body(SessionCreate)
    if payload.difficulty_min > payload.difficulty_max:
        raise ApiError("difficulty_min не может превышать difficulty_max", 422)

    session = TrainingSession(
        title=payload.title,
        teacher_id=principal.id,
        group_id=payload.group_id,
        mode=SessionMode(payload.mode),
        question_source=QuestionSource(payload.question_source),
        status=SessionStatus.PLANNED,
        grading_profile_id=payload.grading_profile_id,
        difficulty_min=payload.difficulty_min,
        difficulty_max=payload.difficulty_max,
        time_limit_sec=payload.time_limit_sec,
        settings={"channel": payload.channel},
    )
    db.session.add(session)
    db.session.flush()
    _set_categories(session, payload.category_ids)

    participant_ids = set(payload.participant_ids)
    if payload.group_id:
        group = get_or_404(Group, payload.group_id, "Группа")
        participant_ids.update(member.id for member in group.members)
    for user_id in participant_ids:
        if db.session.get(User, user_id) is not None:
            db.session.add(SessionParticipant(session_id=session.id, user_id=user_id))

    write_audit(
        db.session,
        request,
        principal,
        "session.create",
        "session",
        session.id,
        {"participants": len(participant_ids), "mode": session.mode.value},
    )
    commit()
    return ok(_session_view(session, principal), 201)


@sessions_bp.get("/sessions")
def list_sessions():
    principal = current_user()
    stmt = select(TrainingSession).order_by(TrainingSession.created_at.desc())

    if is_student(principal):
        stmt = stmt.join(
            SessionParticipant, SessionParticipant.session_id == TrainingSession.id
        ).where(SessionParticipant.user_id == principal.id)
    elif not is_admin(principal):
        stmt = stmt.where(TrainingSession.teacher_id == principal.id)

    status = request.args.get("status")
    if status:
        try:
            stmt = stmt.where(TrainingSession.status == SessionStatus(status))
        except ValueError:
            raise ApiError("Некорректный status", 422)
    group_id = uuid_arg("group_id")
    if group_id:
        stmt = stmt.where(TrainingSession.group_id == group_id)

    return ok(paginate(stmt, serializer=lambda row: _session_view(row, principal)))


@sessions_bp.get("/sessions/<uuid:session_id>")
def get_session(session_id):
    principal = current_user()
    return ok(_session_view(_visible_session(session_id, principal), principal))


@sessions_bp.patch("/sessions/<uuid:session_id>")
def update_session(session_id):
    principal = require("session.manage")
    session = _owned_session(session_id, principal)
    if session.status is not SessionStatus.PLANNED:
        raise ApiError("Изменять можно только запланированное занятие", 409)

    payload = body(SessionUpdate)
    for name in (
        "title",
        "difficulty_min",
        "difficulty_max",
        "time_limit_sec",
        "grading_profile_id",
    ):
        value = getattr(payload, name, None)
        if value is not None:
            setattr(session, name, value)
    if payload.category_ids is not None:
        _set_categories(session, payload.category_ids)
    if payload.channel:
        session.settings = {**(session.settings or {}), "channel": payload.channel}
    if session.difficulty_min > session.difficulty_max:
        raise ApiError("difficulty_min не может превышать difficulty_max", 422)

    write_audit(db.session, request, principal, "session.update", "session", session.id)
    commit()
    return ok(_session_view(session, principal))


@sessions_bp.post("/sessions/<uuid:session_id>/participants")
def add_participants(session_id):
    principal = require("session.manage")
    session = _owned_session(session_id, principal)
    payload = body(MembersIn)
    added = 0
    for user_id in payload.user_ids:
        if db.session.get(User, user_id) is None:
            continue
        if db.session.get(SessionParticipant, (session.id, user_id)) is None:
            db.session.add(SessionParticipant(session_id=session.id, user_id=user_id))
            added += 1
    write_audit(
        db.session,
        request,
        principal,
        "session.add_participants",
        "session",
        session.id,
        {"added": added},
    )
    commit()
    return ok(_session_view(session, principal))


@sessions_bp.delete("/sessions/<uuid:session_id>/participants/<uuid:user_id>")
def remove_participant(session_id, user_id):
    principal = require("session.manage")
    session = _owned_session(session_id, principal)
    participant = db.session.get(SessionParticipant, (session.id, user_id))
    if participant is None:
        raise ApiError("Участник не найден", 404)
    db.session.delete(participant)
    write_audit(
        db.session,
        request,
        principal,
        "session.remove_participant",
        "session",
        session.id,
        {"user_id": str(user_id)},
    )
    commit()
    return ok(_session_view(session, principal))


@sessions_bp.post("/sessions/<uuid:session_id>/start")
def start_session(session_id):
    principal = require("session.manage")
    session = _owned_session(session_id, principal)
    if session.status is not SessionStatus.PLANNED:
        raise ApiError("Занятие уже запущено или завершено", 409)
    if not session.participants:
        raise ApiError("В занятии нет ни одного обучающегося", 409)

    limit = int(settings.get("perf.max_active_sessions", 0) or 0)
    if limit:
        running = db.session.execute(
            select(func.count())
            .select_from(TrainingSession)
            .where(TrainingSession.status == SessionStatus.RUNNING)
        ).scalar_one()
        if running >= limit:
            raise ApiError(
                f"Достигнут предел одновременных занятий ({limit})",
                409,
                code="capacity_reached",
            )

    session.status = SessionStatus.RUNNING
    session.started_at = datetime.now(timezone.utc)
    write_audit(db.session, request, principal, "session.start", "session", session.id)
    commit()
    return ok(_session_view(session, principal))


@sessions_bp.post("/sessions/<uuid:session_id>/finish")
def finish_session(session_id):
    principal = require("session.manage")
    session = _owned_session(session_id, principal)
    if session.status is SessionStatus.FINISHED:
        raise ApiError("Занятие уже завершено", 409)

    session.status = SessionStatus.FINISHED
    session.finished_at = datetime.now(timezone.utc)

    expired = 0
    hangups = []
    open_attempts = db.session.execute(
        select(Attempt).where(
            Attempt.session_id == session.id,
            Attempt.status.in_([AttemptStatus.ISSUED, AttemptStatus.IN_PROGRESS]),
        )
    ).scalars()
    for attempt in open_attempts:
        attempt.status = AttemptStatus.EXPIRED
        expired += 1
        for call in attempt.calls:
            if call.status is not CallStatus.FINISHED:
                call.status = CallStatus.FINISHED
                call.finish_at = session.finished_at
                hangups.append(call.sip_call_id)

    write_audit(
        db.session,
        request,
        principal,
        "session.finish",
        "session",
        session.id,
        {"expired_attempts": expired},
    )
    commit()
    for sip_call_id in hangups:  # сетевые вызовы - после фиксации в БД
        integrations.hangup(sip_call_id)
    return ok(_session_view(session, principal))


@sessions_bp.get("/sessions/<uuid:session_id>/monitor")
def monitor_session(session_id):
    principal = require("session.manage")
    session = _owned_session(session_id, principal)
    attempts = list(
        db.session.execute(
            select(Attempt)
            .where(Attempt.session_id == session.id)
            .order_by(Attempt.issued_at.desc())
            .limit(500)
        ).scalars()
    )

    scored = [a for a in attempts if a.final_score is not None]
    active = [
        a
        for a in attempts
        if a.status in {AttemptStatus.ISSUED, AttemptStatus.IN_PROGRESS}
    ]
    return ok(
        {
            "session_id": str(session.id),
            "status": session.status.value,
            "server_time": datetime.now(timezone.utc).isoformat(),
            "attempts_total": len(attempts),
            "in_progress": len(active),
            "avg_score": (
                round(sum(a.final_score for a in scored) / len(scored), 2)
                if scored
                else None
            ),
            "items": [
                {
                    "attempt_id": str(a.id),
                    "user_id": str(a.user_id),
                    "full_name": a.user.full_name if a.user else None,
                    "seq": a.seq,
                    "status": a.status.value,
                    "score": a.final_score,
                    "passed": a.passed,
                    "duration_ms": a.duration_ms,
                    "time_limit_sec": a.time_limit_sec,
                    "issued_at": a.issued_at.isoformat(),
                }
                for a in attempts
            ],
        }
    )


@sessions_bp.get("/sessions/<uuid:session_id>/attempts")
def list_session_attempts(session_id):
    principal = current_user()
    session = _visible_session(session_id, principal)
    stmt = (
        select(Attempt)
        .where(Attempt.session_id == session.id)
        .order_by(Attempt.issued_at.desc())
    )
    if is_student(principal):
        stmt = stmt.where(Attempt.user_id == principal.id)
    user_id = uuid_arg("user_id")
    if user_id:
        stmt = stmt.where(Attempt.user_id == user_id)
    return ok(paginate(stmt))


@sessions_bp.post("/sessions/<uuid:session_id>/attempts/next")
def next_card(session_id):
    principal = require("session.participate")
    session = get_or_404(TrainingSession, session_id, "Занятие")
    if session.status is not SessionStatus.RUNNING:
        raise ApiError("Занятие не активно", 409, code="session_not_running")
    participant = db.session.get(
        SessionParticipant, (session.id, principal.id), with_for_update=True
    )
    if participant is None:
        raise ApiError("Вы не участник этого занятия", 403)

    open_attempt = (
        db.session.execute(
            select(Attempt).where(
                Attempt.session_id == session.id,
                Attempt.user_id == principal.id,
                Attempt.status.in_([AttemptStatus.ISSUED, AttemptStatus.IN_PROGRESS]),
            )
        )
        .scalars()
        .first()
    )
    if open_attempt is not None:
        raise ApiError(
            "Есть незавершенная карточка",
            409,
            code="attempt_in_progress",
            details={"attempt_id": str(open_attempt.id)},
        )

    seq = (
        db.session.execute(
            select(func.coalesce(func.max(Attempt.seq), 0)).where(
                Attempt.session_id == session.id, Attempt.user_id == principal.id
            )
        ).scalar_one()
        + 1
    )

    scenario = _pick_scenario(session, principal)
    profile = _resolve_profile(session, scenario)
    time_limit = resolve_time_limit(
        session, scenario, profile, current_app.config["DEFAULT_TIME_LIMIT_SEC"]
    )

    attempt = Attempt(
        session_id=session.id,
        user_id=principal.id,
        scenario_id=scenario.id,
        seq=seq,
        status=AttemptStatus.ISSUED,
        time_limit_sec=time_limit,
        forecast_score=analytics.forecast_next_attempt(principal.id),
        answer={},
        actions=[],
    )
    db.session.add(attempt)
    db.session.flush()

    channel = (session.settings or {}).get("channel", "text")
    call = Call(
        attempt_id=attempt.id,
        channel=CallChannel.TEXT,
        caller_number=integrations.caller_number(attempt.id),
        status=CallStatus.RINGING,
    )
    db.session.add(call)
    db.session.flush()
    for line in (scenario.legend or {}).get("dialog", []) or []:
        db.session.add(CallMessage(call_id=call.id, author="caller", text=line))

    template = db.session.get(CardTemplate, scenario.template_id)
    write_audit(
        db.session,
        request,
        principal,
        "attempt.issue",
        "attempt",
        attempt.id,
        {"scenario_id": str(scenario.id), "seq": seq},
    )
    commit()

    # Звонок - только после коммита: события от arm_voip (в т.ч. быстрый неответ)
    # должны находить строку calls, иначе состояние останется «звонит».
    info = integrations.start_call(
        attempt.id,
        channel,
        principal.username,
        caller_hint=call.caller_number,
        audio=(scenario.legend or {}).get("audio"),
    )
    if info["channel"] == "voip":
        call.channel = CallChannel.VOIP
        call.sip_call_id = info["sip_call_id"]
        commit()

    return ok(
        {
            "attempt": attempt.to_dict(),
            "call": {
                **call.to_dict(),
                "degraded": info["degraded"],
                "sip_server": info["sip_server"],
                "sip": info["sip"],
                "ring_timeout_sec": info.get("ring_timeout_sec"),
            },
            "scenario": {
                "id": str(scenario.id),
                "category_id": scenario.category_id,
                "difficulty": scenario.difficulty,
                "legend": {
                    k: v
                    for k, v in (scenario.legend or {}).items()
                    if k not in HIDDEN_FROM_STUDENT
                },
            },
            "template_fields": template.fields if template else [],
            "time_limit_sec": attempt.time_limit_sec,
        },
        201,
    )


@sessions_bp.post("/attempts/<uuid:attempt_id>/answer")
def answer_call(attempt_id):
    principal = require("session.participate")
    attempt = get_or_404(Attempt, attempt_id, "Карточка", lock=True)
    if attempt.user_id != principal.id:
        raise ApiError("Карточка другого обучающегося", 403)
    if attempt.status is not AttemptStatus.ISSUED:
        raise ApiError("Вызов уже принят или карточка закрыта", 409)

    now = datetime.now(timezone.utc)
    attempt.started_at = now
    attempt.status = AttemptStatus.IN_PROGRESS

    call = (
        db.session.execute(select(Call).where(Call.attempt_id == attempt.id))
        .scalars()
        .first()
    )
    if call is not None:
        ring_at = (
            call.ring_at
            if call.ring_at.tzinfo
            else call.ring_at.replace(tzinfo=timezone.utc)
        )
        call.status = CallStatus.ANSWERED
        if call.answer_at is None:  # при VoIP время ответа уже пришло от arm_voip
            call.answer_at = now
            call.answer_delay_ms = int((now - ring_at).total_seconds() * 1000)

    commit()
    return ok(
        {
            "attempt": attempt.to_dict(),
            "call": call.to_dict() if call else None,
            "messages": [m.to_dict() for m in (call.messages if call else [])],
        }
    )


@sessions_bp.post("/attempts/<uuid:attempt_id>/messages")
def send_message(attempt_id):
    principal = require("session.participate")
    attempt = get_or_404(Attempt, attempt_id, "Карточка")
    if attempt.user_id != principal.id:
        raise ApiError("Карточка другого обучающегося", 403)
    if attempt.status is not AttemptStatus.IN_PROGRESS:
        raise ApiError("Диалог доступен только по принятому вызову", 409)

    payload = body(CallMessageIn)
    call = (
        db.session.execute(select(Call).where(Call.attempt_id == attempt.id))
        .scalars()
        .first()
    )
    if call is None:
        raise ApiError("Вызов не найден", 404)

    turn = db.session.execute(
        select(func.count(CallMessage.id)).where(
            CallMessage.call_id == call.id, CallMessage.author == "operator"
        )
    ).scalar_one()
    db.session.add(CallMessage(call_id=call.id, author="operator", text=payload.text))
    scenario = db.session.get(Scenario, attempt.scenario_id)
    reply = integrations.caller_reply(
        scenario.legend if scenario else {}, payload.text, turn
    )
    message = CallMessage(call_id=call.id, author="caller", text=reply)
    db.session.add(message)
    commit()
    return ok(
        {"reply": message.to_dict(), "messages": [m.to_dict() for m in call.messages]},
        201,
    )


@sessions_bp.get("/attempts/<uuid:attempt_id>/messages")
def list_messages(attempt_id):
    principal = current_user()
    attempt = get_or_404(Attempt, attempt_id, "Карточка")
    if is_student(principal) and attempt.user_id != principal.id:
        raise ApiError("Карточка другого обучающегося", 403)
    call = (
        db.session.execute(select(Call).where(Call.attempt_id == attempt.id))
        .scalars()
        .first()
    )
    if call is None:
        raise ApiError("Вызов не найден", 404)
    return ok(
        {"call": call.to_dict(), "messages": [m.to_dict() for m in call.messages]}
    )


@sessions_bp.put("/attempts/<uuid:attempt_id>/draft")
def save_draft(attempt_id):
    """Промежуточное сохранение введенного и выполненных действий (ТЗ: «сохранять
    промежуточные результаты»). Оценки не вызывает, таймер не останавливает."""
    principal = require("attempt.submit")
    attempt = get_or_404(Attempt, attempt_id, "Карточка", lock=True)
    if attempt.user_id != principal.id:
        raise ApiError("Карточка другого обучающегося", 403)
    if attempt.status is not AttemptStatus.IN_PROGRESS:
        raise ApiError(
            "Черновик можно сохранять только по принятому вызову",
            409,
            code="not_in_progress",
        )
    payload = body(SubmitIn)
    attempt.answer = payload.answer
    attempt.actions = payload.actions
    commit()
    return ok(
        {
            "attempt_id": str(attempt.id),
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
    )


def resolve_time_limit(session, scenario, profile, default):
    """Лимит времени карточки. Приоритет: занятие, сценарий, профиль оценивания,
    затем значение по умолчанию (ТЗ: 30 с). Заданный явно лимит более
    конкретного уровня всегда важнее общего."""
    for source in (session, scenario):
        if source is not None and source.time_limit_sec:
            return source.time_limit_sec
    if profile is not None and profile.default_time_limit_sec:
        return profile.default_time_limit_sec
    return default


def process_submission(attempt, principal, answer, actions, now, req):
    """Оценка отправленной карточки. Общая для обычного запроса и для повторной
    обработки из буфера (services/spool.py). Коммит и hangup - на вызывающем.
    now - момент, когда ответ принят: при повторной обработке это время
    получения, а не время восстановления БД, поэтому норматив считается честно.
    Возвращает id звонка для завершения в VoIP.
    """
    started = attempt.started_at or attempt.issued_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)

    attempt.submitted_at = now
    attempt.duration_ms = max(0, int((now - started).total_seconds() * 1000))
    attempt.answer = answer
    attempt.actions = actions
    attempt.status = AttemptStatus.SUBMITTED

    scenario = db.session.get(Scenario, attempt.scenario_id)
    template = db.session.get(CardTemplate, scenario.template_id)
    session = db.session.get(TrainingSession, attempt.session_id)
    profile = _resolve_profile(session, scenario)

    grammar_issues = []
    if profile is None or profile.grammar_check_enabled:
        grammar_issues = grammar.check_answer(
            answer,
            template.fields if template else [],
            rules=(profile.syntax_rules if profile else None),
            known_words=grammar.words_of(
                scenario.title,
                *(scenario.reference_card or {}).values(),
                *[
                    v
                    for v in (scenario.legend or {}).values()
                    if isinstance(v, (str, list))
                ],
            ),
        )

    verdict = scoring.evaluate(
        template_fields=template.fields if template else [],
        reference_card=scenario.reference_card,
        # в режиме «заполнение карточек» шаги работы с карточкой не оцениваются
        reference_actions=(
            [] if session.mode is SessionMode.CARDS else scenario.reference_actions
        ),
        answer=answer,
        actions=actions,
        duration_ms=attempt.duration_ms,
        time_limit_sec=attempt.time_limit_sec,
        grammar_errors=grammar_issues,
        profile=profile,
        default_pass_score=current_app.config["DEFAULT_PASS_SCORE"],
        semantic_judge=ai.semantic_equal if ai.scoring_enabled() else None,
    )

    attempt.score = round(verdict.score, 2)
    attempt.passed = verdict.passed
    attempt.evaluation = {
        **verdict.to_dict(),
        "scenario_title": scenario.title,
        "category_id": scenario.category_id,
    }
    attempt.evaluated_by = EvaluationSource.AI
    attempt.evaluated_at = now
    attempt.ai_model = scoring.ENGINE + (
        "+" + ai.model_name() if ai.scoring_enabled() else ""
    )
    attempt.status = AttemptStatus.EVALUATED

    for error in verdict.errors:
        db.session.add(
            AttemptError(
                attempt_id=attempt.id,
                kind=ErrorKind(error["kind"]),
                field_key=error.get("field_key"),
                severity=int(error.get("severity", 1)),
                message=error.get("message", ""),
                expected=error.get("expected"),
                actual=error.get("actual"),
                position=error.get("position"),
            )
        )

    call = (
        db.session.execute(select(Call).where(Call.attempt_id == attempt.id))
        .scalars()
        .first()
    )
    hangup_id = None
    if call is not None:
        call.status = CallStatus.FINISHED
        call.finish_at = now
        hangup_id = call.sip_call_id

    write_audit(
        db.session,
        req,
        principal,
        "attempt.submit",
        "attempt",
        attempt.id,
        {"score": float(attempt.score), "passed": bool(attempt.passed)},
    )
    return hangup_id


@sessions_bp.post("/attempts/<uuid:attempt_id>/submit")
def submit_card(attempt_id):
    principal = require("attempt.submit")
    attempt = get_or_404(Attempt, attempt_id, "Карточка", lock=True)
    if attempt.user_id != principal.id:
        raise ApiError("Карточка другого обучающегося", 403)
    if attempt.status in {AttemptStatus.SUBMITTED, AttemptStatus.EVALUATED}:
        raise ApiError("Карточка уже отправлена", 409)
    if attempt.status is AttemptStatus.EXPIRED:
        raise ApiError("Занятие завершено, карточка закрыта", 409)
    if attempt.status is AttemptStatus.ISSUED:
        raise ApiError(
            "Сначала примите вызов: время на карточку отсчитывается с ответа",
            409,
            code="call_not_answered",
        )

    payload = body(SubmitIn)
    hangup_id = process_submission(
        attempt,
        principal,
        payload.answer,
        payload.actions,
        datetime.now(timezone.utc),
        request,
    )
    commit()
    integrations.hangup(hangup_id)  # сетевой вызов - после фиксации в БД
    return ok(_attempt_result(attempt))


def _attempt_result(attempt):
    return {
        "attempt_id": str(attempt.id),
        "session_id": str(attempt.session_id),
        "seq": attempt.seq,
        "status": attempt.status.value,
        "score": attempt.final_score,
        "auto_score": float(attempt.score) if attempt.score is not None else None,
        "expert_score": (
            float(attempt.expert_score) if attempt.expert_score is not None else None
        ),
        "expert_comment": attempt.expert_comment,
        "passed": attempt.passed,
        "duration_ms": attempt.duration_ms,
        "time_limit_sec": attempt.time_limit_sec,
        "delta_sec": round((attempt.time_overrun_ms or 0) / 1000, 1),
        "breakdown": attempt.evaluation or {},
        "errors": [e.to_dict() for e in attempt.errors],
    }


@sessions_bp.get("/attempts/<uuid:attempt_id>")
def get_attempt(attempt_id):
    principal = current_user()
    attempt = get_or_404(Attempt, attempt_id, "Карточка")
    if is_student(principal) and attempt.user_id != principal.id:
        raise ApiError("Результаты других обучающихся недоступны", 403)
    if is_student(principal) and attempt.status is not AttemptStatus.EVALUATED:
        raise ApiError("Карточка еще не оценена", 409)
    result = _attempt_result(attempt)
    if not is_student(principal):
        scenario = db.session.get(Scenario, attempt.scenario_id)
        result["answer"] = attempt.answer
        result["actions"] = attempt.actions
        result["reference_card"] = scenario.reference_card if scenario else None
        result["reference_actions"] = scenario.reference_actions if scenario else None
    return ok(result)


def _as_text(value):
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return "" if value is None else str(value).strip()


def _action_types(actions):
    types = [a.get("type") if isinstance(a, dict) else a for a in actions or []]
    return [t for t in types if t in card_schema.ACTION_TYPES]


@sessions_bp.post("/attempts/<uuid:attempt_id>/scenario")
def promote_attempt(attempt_id):
    """Делает из оцененной карточки обучающегося новый сценарий (ТЗ: «сформированные
    обучающимися карточки»). Сценарий уходит на утверждение преподавателю, после
    утверждения попадает в занятия с источником student или mixed."""
    principal = require("scenario.manage")
    attempt = get_or_404(Attempt, attempt_id, "Карточка")
    _owned_session(attempt.session_id, principal)
    if attempt.status is not AttemptStatus.EVALUATED:
        raise ApiError("Использовать можно только оцененную карточку", 409)
    if db.session.execute(
        select(Scenario.id).where(Scenario.source_attempt_id == attempt.id)
    ).first():
        raise ApiError("Сценарий из этой карточки уже создан", 409)

    source = db.session.get(Scenario, attempt.scenario_id)
    template = db.session.get(CardTemplate, source.template_id)
    keys = [f["key"] for f in (template.fields if template else []) if f.get("key")]
    card = {
        k: _as_text((attempt.answer or {}).get(k))
        for k in keys
        if _as_text((attempt.answer or {}).get(k))
    }
    if not card:
        raise ApiError("В карточке нет заполненных полей", 422)

    scenario = Scenario(
        title=f"{source.title} (карточка обучающегося)"[:255],
        category_id=source.category_id,
        template_id=source.template_id,
        difficulty=source.difficulty,
        origin=ScenarioOrigin.STUDENT,
        status=ScenarioStatus.PENDING_REVIEW,
        legend=source.legend,
        reference_card=card,
        reference_actions=_action_types(attempt.actions) or source.reference_actions,
        time_limit_sec=attempt.time_limit_sec,
        grading_profile_id=source.grading_profile_id,
        source_attempt_id=attempt.id,
        author_id=principal.id,
    )
    db.session.add(scenario)
    db.session.flush()
    write_audit(
        db.session,
        request,
        principal,
        "scenario.from_attempt",
        "scenario",
        scenario.id,
        {"attempt_id": str(attempt.id)},
    )
    commit()
    return ok(scenario.to_dict(), 201)


@sessions_bp.post("/attempts/<uuid:attempt_id>/grade")
def grade_attempt(attempt_id):
    principal = require("attempt.grade")
    attempt = get_or_404(Attempt, attempt_id, "Карточка", lock=True)
    _owned_session(attempt.session_id, principal)
    if attempt.status is not AttemptStatus.EVALUATED:
        raise ApiError("Оценивать можно только отправленную карточку", 409)
    payload = body(ExpertGradeIn)

    old_score = (
        float(attempt.expert_score) if attempt.expert_score is not None else None
    )
    attempt.expert_id = principal.id
    attempt.expert_score = payload.score
    attempt.expert_comment = payload.comment
    attempt.expert_reviewed_at = datetime.now(timezone.utc)
    attempt.evaluated_by = EvaluationSource.HYBRID

    write_audit(
        db.session,
        request,
        principal,
        "attempt.grade",
        "attempt",
        attempt.id,
        {"old": old_score, "new": payload.score, "auto": float(attempt.score or 0)},
    )
    commit()
    return ok(_attempt_result(attempt))
