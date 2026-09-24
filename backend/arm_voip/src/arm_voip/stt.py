"""Распознавание реплики оператора: пересылает запись сервису voice."""

import logging
import os

import httpx

from .config import Config

logger = logging.getLogger(__name__)


def transcribe(path: str) -> str | None:
    """Возвращает распознанный текст, либо None (STT выключен, файла нет,
    тишина или сервис недоступен) - тогда реплика просто пропускается."""
    if not Config.VOICE_DIALOG_ENABLED or not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as handle:
            files = {"audio": (os.path.basename(path), handle, "audio/wav")}
            with httpx.Client(
                base_url=Config.VOICE_BASE_URL, timeout=Config.VOICE_STT_TIMEOUT_SEC
            ) as client:
                response = client.post(
                    "/stt",
                    files=files,
                    headers={"X-Service-Token": Config.VOICE_SERVICE_TOKEN},
                )
        if response.status_code != 200:
            logger.warning(
                "voice отклонил распознавание (%s): %s",
                response.status_code,
                response.text[:200],
            )
            return None
        text = (response.json().get("text") or "").strip()
        return text or None
    except (httpx.HTTPError, OSError) as exc:
        logger.warning("Сервис voice недоступен для распознавания: %s", exc)
        return None
