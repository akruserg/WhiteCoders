import hashlib
import random

import httpx
from flask import current_app
from sqlalchemy import select

from ..core.config import Config
from ..core.extensions import db
from ..models import CallMessage, SystemSetting
from . import ai

VOIP_SETTING_KEY = "voip.enabled"


class ArmVoipError(RuntimeError):
    """arm_voip недоступен или отклонил запрос."""


def _caller_number(seed):
    digest = hashlib.sha256(str(seed).encode()).hexdigest()
    tail = int(digest[:7], 16) % 10_000_000
    return f"+7495{tail:07d}"


def caller_number(attempt_id, hint=None):
    return hint or _caller_number(attempt_id)


def voip_available():
    """VoIP включен переменной окружения, администратор может переопределить
    это в настройке voip.enabled (общая для всех воркеров, в отличие от памяти).
    """
    override = db.session.execute(
        select(SystemSetting.value).where(SystemSetting.key == VOIP_SETTING_KEY)
    ).scalar()
    if override is not None:
        return bool(override)
    return bool(current_app.config["VOIP_ENABLED"])


def _client():
    return httpx.Client(
        base_url=Config.ARM_VOIP_BASE_URL,
        timeout=Config.ARM_VOIP_TIMEOUT_SEC,
        headers={"X-Service-Token": Config.ARM_VOIP_SERVICE_TOKEN},
    )


def _text_call(channel, number, degraded):
    return {
        "channel": "text",
        "requested_channel": channel,
        "degraded": degraded,
        "caller_number": number,
        "sip_call_id": None,
        "latency_ms": None,
        "sip_server": None,
        "sip": None,
    }


def start_call(
    attempt_id,
    channel="text",
    operator=None,
    caller_hint=None,
    audio=None,
):
    """Создает вызов. При недоступном VoIP занятие продолжается текстом."""
    number = caller_number(attempt_id, caller_hint)

    if channel != "voip":
        return _text_call(channel, number, degraded=False)
    if not voip_available():
        return _text_call(channel, number, degraded=True)

    try:
        with _client() as client:
            response = client.post(
                "/calls",
                json={
                    "attempt_id": str(attempt_id),
                    "operator": operator or "",
                    "destination": Config.VOIP_DESTINATION or None,
                    "audio": audio or None,
                    "caller_number": number,
                },
            )
        if response.status_code >= 400:
            raise ArmVoipError(
                f"arm_voip отклонил start_call "
                f"({response.status_code}): {response.text}"
            )
        data = response.json()
    except (httpx.HTTPError, ArmVoipError) as exc:
        current_app.logger.warning(
            "arm_voip недоступен, звонок %s идет в текстовом режиме: %s",
            attempt_id,
            exc,
        )
        return _text_call(channel, number, degraded=True)

    sip = data.get("sip")
    return {
        "channel": "voip",
        "requested_channel": channel,
        "degraded": False,
        "caller_number": number,
        "sip_call_id": data.get("call_id"),
        "latency_ms": None,
        "sip_server": (sip or {}).get("ws_url"),
        "sip": sip,
        "ring_timeout_sec": data.get("ring_timeout_sec"),
    }


def hangup(sip_call_id=None):
    if not sip_call_id or not voip_available():
        return {"status": "finished", "sip_call_id": sip_call_id}

    try:
        with _client() as client:
            response = client.delete(f"/calls/{sip_call_id}")
        if response.status_code >= 400:
            raise ArmVoipError(
                f"arm_voip отклонил hangup ({response.status_code}): {response.text}"
            )
    except (httpx.HTTPError, ArmVoipError) as exc:
        current_app.logger.warning(
            "Не удалось завершить звонок %s через arm_voip: %s", sip_call_id, exc
        )

    return {"status": "finished", "sip_call_id": sip_call_id}


def voip_health():
    if not voip_available():
        return {"available": False, "provider": None, "reason": "disabled"}

    try:
        with _client() as client:
            response = client.get("/health")
        if response.status_code >= 400:
            return {"available": False, "error": f"HTTP {response.status_code}"}
        return {"available": True, **response.json()}
    except httpx.HTTPError as exc:
        current_app.logger.warning("arm_voip healthcheck failed: %s", exc)
        return {"available": False, "error": str(exc)}


def _scripted_reply(scenario_legend, turn):
    """Заготовки из сценария - запасной путь, если ИИ выключен или недоступен."""
    dialog = list((scenario_legend or {}).get("dialog") or [])
    followups = list((scenario_legend or {}).get("followups") or [])

    if turn < len(followups):
        return followups[turn]

    if not dialog:
        return "Больше добавить нечего."

    return random.choice(
        [
            "Да, все верно.",
            "Я уже все сказал(а), приезжайте скорее.",
            "Повторю: " + dialog[-1],
        ]
    )


def caller_reply(scenario_legend, operator_text, turn=0, history=None):
    """Реплика «заявителя» на слова оператора: живая генерация нейросетью
    (учитывает легенду и историю разговора), а если ИИ выключен или не
    ответил - заготовки из сценария (turn - сколько реплик оператора уже
    было, 0 - первая).
    """
    if ai.is_enabled():
        try:
            return ai.caller_turn(scenario_legend, history or [], operator_text, turn)
        except ai.AiUnavailable as exc:
            current_app.logger.info(
                "Живая реплика заявителя недоступна, использую заготовку: %s", exc
            )
    return _scripted_reply(scenario_legend, turn)


def record_dialog_turn(call, scenario, operator_text):
    """Добавляет в стенограмму звонка реплику оператора и ответ заявителя.
    Общая точка входа для текстового чата (routes/sessions.py) и голосового
    диалога (routes/internal.py, реплика уже распознана STT в arm_voip)."""
    history = [
        {"author": m.author, "text": m.text}
        for m in sorted(call.messages, key=lambda m: m.created_at)
    ]
    turn = sum(1 for m in history if m["author"] == "operator")

    db.session.add(CallMessage(call_id=call.id, author="operator", text=operator_text))
    reply_text = caller_reply(
        scenario.legend if scenario else {}, operator_text, turn, history
    )
    reply = CallMessage(call_id=call.id, author="caller", text=reply_text)
    db.session.add(reply)
    return reply
