"""
POST /internal/voip/events            - события звонков от arm_voip
                                        (ответ, завершение, неответ, задержка)
POST /internal/calls/<id>/voice-turn  - реплика оператора (распознана STT в
                                        arm_voip) -> ответ заявителя (ИИ)

Служебные маршруты: без JWT, доступ по общему токену X-Service-Token.
"""

import hmac
from datetime import datetime, timezone

from flask import Blueprint, current_app, request
from sqlalchemy import select

from ..core.errors import ApiError
from ..core.extensions import db
from ..core.security import log_event
from ..models import Call, CallStatus, Scenario
from ..schemas import VoipEventIn, VoiceTurnIn
from ..services import alerts, integrations, settings
from ._helpers import body, commit, ok

internal_bp = Blueprint("internal", __name__)


def _require_service_token():
    expected = current_app.config.get("ARM_VOIP_SERVICE_TOKEN") or ""
    if not expected:
        raise ApiError("Служебный токен VoIP не настроен", 503)
    given = request.headers.get("X-Service-Token", "")
    if not hmac.compare_digest(given, expected):
        raise ApiError("Неверный служебный токен", 401, code="unauthenticated")


def _aware(value):
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _apply_answered(call, when):
    if call.answer_at is None:
        call.answer_at = when
        call.answer_delay_ms = max(
            0, int((when - _aware(call.ring_at)).total_seconds() * 1000)
        )
    if call.status is CallStatus.RINGING:
        call.status = CallStatus.ANSWERED


def _apply_finished(call, payload, when):
    if call.finish_at is None:
        call.finish_at = when
    call.status = (
        CallStatus.MISSED if payload.event == "no_answer" else CallStatus.FINISHED
    )
    if payload.rtt_ms is not None:
        call.rtt_ms = int(round(payload.rtt_ms))


def _report_latency(call, payload):
    if payload.latency_ok is not False:
        return
    limit = settings.get(
        "voip.max_latency_ms", current_app.config["VOIP_MAX_LATENCY_MS"]
    )
    log_event(
        "voip",
        "warning",
        f"Задержка голоса выше нормы {limit} мс",
        {
            "call_id": str(call.id),
            "rtt_avg_ms": payload.rtt_ms,
            "rtt_max_ms": payload.rtt_max_ms,
        },
    )
    alerts.raise_alert(
        "voip",
        f"Задержка передачи голоса превышает {limit} мс",
        fingerprint="voip.latency",
        details={"rtt_max_ms": payload.rtt_max_ms, "call_id": str(call.id)},
    )


@internal_bp.post("/internal/voip/events")
def voip_event():
    _require_service_token()
    payload = body(VoipEventIn)

    call = (
        db.session.execute(select(Call).where(Call.sip_call_id == payload.call_id))
        .scalars()
        .first()
    )
    if call is None:
        # чужой или уже удаленный звонок: повторять отправку бессмысленно
        return ok({"status": "ignored"})

    when = (
        datetime.fromtimestamp(payload.at, tz=timezone.utc)
        if payload.at
        else datetime.now(timezone.utc)
    )

    if payload.extension:
        call.asterisk_channel = f"PJSIP/{payload.extension}"

    if payload.event == "answered":
        _apply_answered(call, when)
    else:
        _apply_finished(call, payload, when)
        _report_latency(call, payload)

    commit()
    return ok({"status": "ok", "call_status": call.status.value})


@internal_bp.post("/internal/calls/<sip_call_id>/voice-turn")
def voice_turn(sip_call_id):
    """Живой голосовой диалог: arm_voip прислал распознанную реплику
    оператора, здесь она попадает в общую стенограмму звонка и получает
    ответ заявителя (см. services.integrations.record_dialog_turn) -
    ту же логику использует и текстовый чат (routes/sessions.py)."""
    _require_service_token()
    payload = body(VoiceTurnIn)

    call = (
        db.session.execute(select(Call).where(Call.sip_call_id == sip_call_id))
        .scalars()
        .first()
    )
    if call is None:
        raise ApiError("Звонок не найден", 404, code="call_not_found")

    scenario = db.session.get(Scenario, call.attempt.scenario_id)
    reply = integrations.record_dialog_turn(call, scenario, payload.text)
    commit()
    return ok({"reply": reply.text})
