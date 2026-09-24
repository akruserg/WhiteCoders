"""Озвучивание реплики заявителя: запрос к сервису voice, результат
кладется в AUDIO_DIR и переиспользуется через уже существующий audio.py
(та же конвертация в формат телефонии и то же имя media для ARI)."""

import hashlib
import logging
import os

import httpx

from .audio import resolve_media
from .config import Config

logger = logging.getLogger(__name__)


def _cache_stem(text: str, voice: str) -> str:
    digest = hashlib.sha1(f"{voice}:{text}".encode()).hexdigest()[:20]
    return f"tts_{digest}"


def synthesize(text: str, voice: str | None = None) -> str | None:
    """Возвращает media-идентификатор для ari.play (см. resolve_media),
    либо None, если TTS выключен, текст пуст или сервис недоступен -
    тогда звонок продолжается без этой реплики (не прерывается)."""
    text = (text or "").strip()
    if not Config.VOICE_DIALOG_ENABLED or not text:
        return None

    voice = voice or Config.TTS_DEFAULT_VOICE
    stem = _cache_stem(text, voice)
    source_path = os.path.join(Config.AUDIO_DIR, stem + ".wav")

    if not os.path.exists(source_path):
        try:
            with httpx.Client(
                base_url=Config.VOICE_BASE_URL, timeout=Config.VOICE_TTS_TIMEOUT_SEC
            ) as client:
                response = client.post(
                    "/tts",
                    json={"text": text, "voice": voice},
                    headers={"X-Service-Token": Config.VOICE_SERVICE_TOKEN},
                )
            if response.status_code != 200:
                logger.warning(
                    "voice отклонил синтез (%s): %s",
                    response.status_code,
                    response.text[:200],
                )
                return None
            os.makedirs(Config.AUDIO_DIR, exist_ok=True)
            tmp = source_path + ".part"
            with open(tmp, "wb") as f:
                f.write(response.content)
            os.replace(tmp, source_path)
        except httpx.HTTPError as exc:
            logger.warning("Сервис voice недоступен для синтеза: %s", exc)
            return None

    return resolve_media(stem)
