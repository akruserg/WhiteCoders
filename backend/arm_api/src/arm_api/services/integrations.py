import hashlib
import random

import httpx
from flask import current_app

from ..core.config import Config


class ArmVoipError(RuntimeError):
    # астериск пал и не отвечает
    pass


def _caller_number(seed):
    digest = hashlib.sha256(str(seed).encode()).hexdigest()
    tail = int(digest[:7], 16) % 10_000_000
    return f"+7495{tail:07d}"


def voip_available():
    return Config.VOIP_ENABLED


def _client():
    return httpx.Client(
        base_url=Config.ARM_VOIP_BASE_URL,
        timeout=Config.ARM_VOIP_TIMEOUT_SEC,
        headers={"X-Service-Token": Config.ARM_VOIP_SERVICE_TOKEN},
    )


def start_call(
    attempt_id,
    channel="text",
    operator=None,
    caller_hint=None,
):
    caller_number = caller_hint or _caller_number(attempt_id)

    if channel != "voip":
        return {
            "channel": "text",
            "requested_channel": channel,
            "degraded": False,
            "caller_number": caller_number,
            "sip_call_id": None,
            "latency_ms": None,
            "sip_server": None,
        }

    if not voip_available():
        return {
            "channel": "text",
            "requested_channel": channel,
            "degraded": True,
            "caller_number": caller_number,
            "sip_call_id": None,
            "latency_ms": None,
            "sip_server": None,
        }

    try:
        with _client() as client:
            response = client.post(
                "/calls",
                json={
                    "attempt_id": str(attempt_id),
                    "operator": operator or "",
                    "destination": Config.VOIP_DESTINATION or None,
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
        return {
            "channel": "text",
            "requested_channel": channel,
            "degraded": True,
            "caller_number": caller_number,
            "sip_call_id": None,
            "latency_ms": None,
            "sip_server": None,
        }

    return {
        "channel": "voip",
        "requested_channel": channel,
        "degraded": False,
        "caller_number": caller_number,
        "sip_call_id": data.get("call_id"),
        "latency_ms": None,
        "sip_server": Config.ARM_VOIP_BASE_URL,
    }


def hangup(sip_call_id=None):
    if not sip_call_id or not voip_available():
        return {
            "status": "finished",
            "sip_call_id": sip_call_id,
        }

    try:
        with _client() as client:
            response = client.delete(f"/calls/{sip_call_id}")
        if response.status_code >= 400:
            raise ArmVoipError(
                f"arm_voip отклонил hangup "
                f"({response.status_code}): {response.text}"
            )
    except (httpx.HTTPError, ArmVoipError) as exc:
        current_app.logger.warning(
            "Не удалось завершить звонок %s через arm_voip: %s",
            sip_call_id,
            exc,
        )

    return {
        "status": "finished",
        "sip_call_id": sip_call_id,
    }


def voip_health():
    if not voip_available():
        return {
            "available": False,
            "provider": None,
            "reason": "disabled",
        }

    try:
        with _client() as client:
            response = client.get("/health")
        if response.status_code >= 400:
            return {
                "available": False,
                "error": f"HTTP {response.status_code}",
            }
        return {"available": True, **response.json()}
    except httpx.HTTPError as exc:
        current_app.logger.warning("arm_voip healthcheck failed: %s", exc)
        return {
            "available": False,
            "error": str(exc),
        }


def caller_reply(scenario_legend, operator_text, turn=0):
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
