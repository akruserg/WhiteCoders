from __future__ import annotations

import random
import uuid
from datetime import datetime, timezone

from flask import Blueprint, Response, jsonify, request
from sqlalchemy import func, select

from ..core.extensions import db
from ..core.errors import ApiError
from ..core.security import current_user, require, write_audit
from ..models import (
    Attempt, AttemptError, AttemptStatus, Call, CallChannel, CallMessage, CallStatus,
    CardTemplate, Group, Scenario, ScenarioStatus, SessionParticipant,
    SessionMode, SessionStatus, TrainingSession, User
)
from ..models.incident_category import user_service_scope
from ..schemas import SessionCreate, SubmitIn, ExpertGradeIn, ValidationError
from ..services import grammar, integrations, scoring

sessions_bp = Blueprint("sessions", __name__, url_prefix="")

def _json(model):
    if hasattr(model, "to_dict"):
        return jsonify(model.to_dict())
    return jsonify(model)

def _validation_error(exc):
    raise ApiError(str(exc), 422)

def _get_owned_session(session_id, principal):
    session = db.session.get(TrainingSession, session_id)
    if session is None:
        raise ApiError("Занятие не найдено", 404)
    if principal.role == "teacher" and session.teacher_id != principal.id:
        raise ApiError("Занятие другого преподавателя", 403)
    return session

@sessions_bp.post("/sessions")
def create_session():
    principal=require("session.manage")
    try: payload=SessionCreate.from_request()
    except ValidationError as e: _validation_error(e)

    try: mode=SessionMode(payload.mode)
    except ValueError: raise ApiError("Некорректный mode",422)

    session=TrainingSession(
        title=payload.title, teacher_id=principal.id, group_id=payload.group_id,
        mode=mode,
        settings={"categories":payload.category_ids,"difficulty":payload.difficulty,
                  "time_limit_sec":payload.time_limit_sec,"channel":payload.channel,
                  "thresholds":{"pass":payload.pass_threshold,
                                "grammar_max_errors":payload.grammar_max_errors}}
    )
    db.session.add(session); db.session.flush()

    participants=set(payload.participant_ids)
    if payload.group_id:
        group=db.session.get(Group,payload.group_id)
        if group is not None:
            participants.update(u.id for u in group.members)

    for user_id in participants:
        if db.session.get(User,user_id):
            db.session.add(SessionParticipant(session_id=session.id,user_id=user_id))

    write_audit(db.session,request,principal,"session.create","session",str(session.id),
                {"participants":len(participants)})
    db.session.commit()
    return _json(session),201

@sessions_bp.get("/sessions")
def list_sessions():
    principal=current_user()
    status_filter=request.args.get("status_filter")
    q=select(TrainingSession).order_by(TrainingSession.created_at.desc()).limit(100)
    if principal.role=="teacher":
        q=q.where(TrainingSession.teacher_id==principal.id)
    elif principal.role=="student":
        q=q.join(SessionParticipant,SessionParticipant.session_id==TrainingSession.id).where(
            SessionParticipant.user_id==principal.id)
    if status_filter:
        try: status_filter=SessionStatus(status_filter)
        except ValueError: raise ApiError("Некорректный status_filter",422)
        q=q.where(TrainingSession.status==status_filter)
    sessions=list(db.session.execute(q).scalars())
    return jsonify([s.to_dict() for s in sessions])

@sessions_bp.post("/sessions/<uuid:session_id>/start")
def start_session(session_id):
    principal=require("session.manage")
    session=_get_owned_session(session_id,principal)
    if session.status != SessionStatus.PLANNED:
        raise ApiError("Занятие уже запущено или завершено",409)
    session.status=SessionStatus.RUNNING
    session.started_at=datetime.now(timezone.utc)
    write_audit(db.session,request,principal,"session.start","session",str(session.id))
    db.session.commit()
    return _json(session)

@sessions_bp.post("/sessions/<uuid:session_id>/finish")
def finish_session(session_id):
    principal=require("session.manage")
    session=_get_owned_session(session_id,principal)
    session.status=SessionStatus.FINISHED
    session.finished_at=datetime.now(timezone.utc)
    rows=db.session.execute(select(Attempt).where(
        Attempt.session_id==session.id,
        Attempt.status.in_([AttemptStatus.ISSUED,AttemptStatus.IN_PROGRESS])) )
    for attempt in rows.scalars(): attempt.status=AttemptStatus.EXPIRED
    write_audit(db.session,request,principal,"session.finish","session",str(session.id))
    db.session.commit()
    return _json(session)

@sessions_bp.get("/sessions/<uuid:session_id>/monitor")
def monitor(session_id):
    principal=require("session.manage")
    session=_get_owned_session(session_id,principal)
    attempts=list(db.session.execute(select(Attempt).where(
        Attempt.session_id==session.id).order_by(Attempt.issued_at)).scalars())
    scored=[a for a in attempts if a.score is not None]
    return jsonify({"session_id":str(session.id),"status":session.status.value,
        "attempts_total":len(attempts),
        "in_progress":sum(a.status in {AttemptStatus.ISSUED,AttemptStatus.IN_PROGRESS} for a in attempts),
        "avg_score":round(sum(float(a.score) for a in scored)/max(1,len(scored)),2),
        "items":[{"attempt_id":str(a.id),"user_id":str(a.user_id),"seq":a.seq,
                  "status":a.status.value,"score":float(a.score) if a.score is not None else None,
                  "duration_ms":a.duration_ms} for a in attempts]})

def _pick_scenario(session,user_id):
    settings=session.settings or {}
    categories=settings.get("categories") or []
    user=db.session.get(User,user_id)
    if user and user.service_scope:
        scope=[c.id for c in user.service_scope]
        categories=[c for c in categories if c in scope] or scope
    q=select(Scenario).where(Scenario.status==ScenarioStatus.VALIDATED)
    if categories: q=q.where(Scenario.category_id.in_(categories))
    if settings.get("difficulty"): q=q.where(Scenario.difficulty==settings["difficulty"])
    scenarios=list(db.session.execute(q.limit(200)).scalars())
    if not scenarios: raise ApiError("Нет утверждённых сценариев для выбранных категорий",409)
    return random.choice(scenarios)

@sessions_bp.post("/sessions/<uuid:session_id>/attempts/next")
def next_card(session_id):
    principal=require("session.participate")
    session=db.session.get(TrainingSession,session_id)
    if session is None or session.status != SessionStatus.RUNNING: raise ApiError("Занятие не активно",409)
    if db.session.get(SessionParticipant,(session_id,principal.id)) is None:
        raise ApiError("Вы не участник занятия",403)
    open_attempt=db.session.execute(select(Attempt).where(
        Attempt.session_id==session_id,Attempt.user_id==principal.id,
        Attempt.status.in_([AttemptStatus.ISSUED,AttemptStatus.IN_PROGRESS]))).scalars().first()
    if open_attempt: raise ApiError("Есть незавершённая карточка",409)
    seq=(db.session.execute(select(func.coalesce(func.max(Attempt.seq),0)).where(
        Attempt.session_id==session_id,Attempt.user_id==principal.id)).scalar_one()+1)
    scenario=_pick_scenario(session,principal.id)
    limit=(session.settings or {}).get("time_limit_sec") or scenario.time_limit_sec
    attempt=Attempt(session_id=session_id,user_id=principal.id,scenario_id=scenario.id,seq=seq,time_limit_sec=limit)
    db.session.add(attempt); db.session.flush()
    channel=(session.settings or {}).get("channel","text")
    try: channel_enum=CallChannel(channel)
    except ValueError: channel_enum=CallChannel.TEXT
    info=integrations.start_call(attempt.id,channel,principal.username)
    call=Call(attempt_id=attempt.id,channel=channel_enum,sip_call_id=info.get("sip_call_id"),
              caller_number=info.get("caller_number"))
    db.session.add(call); db.session.flush()
    for line in (scenario.legend or {}).get("dialog",[]):
        db.session.add(CallMessage(call_id=call.id,author="caller",text=line))
    template=db.session.get(CardTemplate,scenario.template_id)
    write_audit(db.session,request,principal,"attempt.issue","attempt",str(attempt.id))
    db.session.commit()
    return jsonify({"attempt":attempt.to_dict(),"call":call.to_dict(),
                    "template_fields":template.fields,"legend":{
                        k:v for k,v in (scenario.legend or {}).items() if k!="reference"}}),201

@sessions_bp.post("/attempts/<uuid:attempt_id>/answer")
def answer_call(attempt_id):
    principal=require("session.participate")
    attempt=db.session.get(Attempt,attempt_id)
    if attempt is None or attempt.user_id!=principal.id: raise ApiError("Карточка не найдена",404)
    if attempt.status!=AttemptStatus.ISSUED: raise ApiError("Вызов уже принят",409)
    now=datetime.now(timezone.utc); attempt.started_at=now; attempt.status=AttemptStatus.IN_PROGRESS
    call=db.session.execute(select(Call).where(Call.attempt_id==attempt_id)).scalars().first()
    if call:
        call.status=CallStatus.ANSWERED; call.answer_at=now
        call.answer_delay_ms=int((now-call.ring_at).total_seconds()*1000)
    db.session.commit(); return _json(attempt)

@sessions_bp.post("/attempts/<uuid:attempt_id>/submit")
def submit(attempt_id):
    principal=require("attempt.submit")
    try: payload=SubmitIn.from_request()
    except ValidationError as e: _validation_error(e)
    attempt=db.session.get(Attempt,attempt_id)
    if attempt is None or attempt.user_id!=principal.id: raise ApiError("Карточка не найдена",404)
    if attempt.status in {AttemptStatus.SUBMITTED,AttemptStatus.EVALUATED}: raise ApiError("Карточка уже отправлена",409)
    now=datetime.now(timezone.utc); start=attempt.started_at or attempt.issued_at
    attempt.submitted_at=now; attempt.duration_ms=int((now-start).total_seconds()*1000)
    attempt.answer=payload.answer; attempt.actions=payload.actions; attempt.status=AttemptStatus.SUBMITTED
    scenario=db.session.get(Scenario,attempt.scenario_id); template=db.session.get(CardTemplate,scenario.template_id)
    session=db.session.get(TrainingSession,attempt.session_id); thresholds=(session.settings or {}).get("thresholds",{})
    grammar_errors=grammar.check_answer(payload.answer,template.fields)
    verdict=scoring.evaluate(template_fields=template.fields,reference_card=scenario.reference_card,
        reference_actions=scenario.reference_actions,answer=payload.answer,actions=payload.actions,
        duration_ms=attempt.duration_ms,time_limit_sec=attempt.time_limit_sec,grammar_errors=grammar_errors,
        pass_threshold=thresholds.get("pass",.7))
    attempt.score=round(verdict.score,2); attempt.passed=verdict.passed; attempt.evaluated_by="auto"
    attempt.status=AttemptStatus.EVALUATED
    attempt.evaluation={**verdict.to_dict(),"scenario_title":scenario.title,
                        "category_code":scenario.category.code if scenario.category else None}
    for err in verdict.errors:
        try: kind=__import__("arm_api.models",fromlist=["ErrorKind"]).ErrorKind(err["kind"])
        except Exception: kind=err["kind"]
        db.session.add(AttemptError(attempt_id=attempt.id,kind=kind,field_key=err.get("field_key"),
            severity=err.get("severity",1),message=err.get("message",""),expected=err.get("expected"),
            actual=err.get("actual")))
    call=db.session.execute(select(Call).where(Call.attempt_id==attempt_id)).scalars().first()
    if call:
        call.status=CallStatus.FINISHED; call.finish_at=now; integrations.hangup(call.sip_call_id)
    write_audit(db.session,request,principal,"attempt.submit","attempt",str(attempt.id),{"score":float(attempt.score)})
    db.session.commit()
    return jsonify({"attempt_id":str(attempt.id),"score":float(attempt.score),"passed":bool(attempt.passed),
        "duration_ms":attempt.duration_ms,"time_limit_sec":attempt.time_limit_sec,
        "delta_sec":round(attempt.duration_ms/1000-attempt.time_limit_sec,1),
        "errors":[e.to_dict() for e in attempt.errors],"breakdown":verdict.to_dict()})

@sessions_bp.get("/attempts/<uuid:attempt_id>")
def get_attempt(attempt_id):
    principal=current_user(); attempt=db.session.get(Attempt,attempt_id)
    if attempt is None: raise ApiError("Карточка не найдена",404)
    if principal.role=="student" and attempt.user_id!=principal.id: raise ApiError("Чужие результаты недоступны",403)
    if attempt.status!=AttemptStatus.EVALUATED: raise ApiError("Карточка ещё не оценена",409)
    return jsonify({"attempt_id":str(attempt.id),"score":float(attempt.score or 0),"passed":bool(attempt.passed),
        "duration_ms":attempt.duration_ms or 0,"time_limit_sec":attempt.time_limit_sec,
        "delta_sec":round((attempt.duration_ms or 0)/1000-attempt.time_limit_sec,1),
        "errors":[e.to_dict() for e in attempt.errors],"breakdown":attempt.evaluation or {}})

@sessions_bp.post("/attempts/<uuid:attempt_id>/grade")
def expert_grade(attempt_id):
    principal=require("attempt.grade")
    try: payload=ExpertGradeIn.from_request()
    except ValidationError as e: _validation_error(e)
    attempt=db.session.get(Attempt,attempt_id)
    if attempt is None: raise ApiError("Карточка не найдена",404)
    old=float(attempt.expert_score) if attempt.expert_score is not None else None
    attempt.expert_score=payload.score; attempt.expert_comment=payload.comment; attempt.evaluated_by="expert"
    write_audit(db.session,request,principal,"grade.change","attempt",str(attempt.id),
                {"old":old,"new":payload.score,"auto":float(attempt.score or 0)})
    db.session.commit(); return _json(attempt)
