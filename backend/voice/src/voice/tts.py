"""Синтез речи заявителя: Piper (ONNX, CPU), модель на русском языке.

Модель грузится в память один раз на процесс (~65 МБ) и переиспользуется -
после прогрева синтез короткой фразы занимает десятые доли секунды.
"""

import io
import logging
import os
import re
import threading
import wave

from .config import Config

logger = logging.getLogger(__name__)

_SAFE_VOICE = re.compile(r"^[\w.\-]{1,128}$")

_lock = threading.Lock()
_voices: dict[str, object] = {}


class TtsError(RuntimeError):
    """Голос не найден или синтез не удался."""


def available_voices() -> list[str]:
    directory = Config.TTS_VOICES_DIR
    if not os.path.isdir(directory):
        return []
    return sorted(
        name[: -len(".onnx")]
        for name in os.listdir(directory)
        if name.endswith(".onnx")
    )


def _load(voice: str):
    if not _SAFE_VOICE.match(voice):
        raise TtsError(f"Недопустимое имя голоса: {voice!r}")
    with _lock:
        model = _voices.get(voice)
        if model is not None:
            return model
        path = os.path.join(Config.TTS_VOICES_DIR, voice + ".onnx")
        if not os.path.exists(path):
            raise TtsError(
                f"Модель голоса {voice!r} не найдена в {Config.TTS_VOICES_DIR}"
                " (запустите download_models.sh)"
            )
        from piper import PiperVoice

        model = PiperVoice.load(path)
        _voices[voice] = model
        logger.info("Голос %s загружен", voice)
        return model


def warm_up(voice: str | None = None) -> None:
    """Первая инициализация ONNX Runtime занимает секунды: делаем это при
    старте сервиса, а не во время первого настоящего звонка."""
    try:
        synthesize("Проверка голоса.", voice or Config.TTS_DEFAULT_VOICE)
    except TtsError as exc:
        logger.warning("Прогрев TTS не удался: %s", exc)


def synthesize(text: str, voice: str | None = None) -> bytes:
    """Возвращает WAV (моно, как отдает Piper - обычно 22050 Гц/16 бит).

    Дальнейшее приведение к формату телефонии (8 кГц) делает вызывающая
    сторона (arm_voip уже умеет это через ffmpeg).
    """
    text = (text or "").strip()
    if not text:
        raise TtsError("Пустой текст")
    text = text[: Config.TTS_MAX_CHARS]
    model = _load(voice or Config.TTS_DEFAULT_VOICE)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        model.synthesize_wav(text, wav_file)
    return buffer.getvalue()
