"""Распознавание речи оператора: faster-whisper (CTranslate2, CPU), офлайн.

Модель грузится один раз на процесс. На CPU занимает больше времени, чем
TTS, поэтому реплика оператора ограничена по длительности на стороне
arm_voip (там же настроено автоматическое завершение записи по тишине).
"""

import logging
import threading

from .config import Config

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_model = None


class SttError(RuntimeError):
    """Модель недоступна или запись не удалось прочитать."""


def _load():
    global _model
    with _lock:
        if _model is not None:
            return _model
        from faster_whisper import WhisperModel

        _model = WhisperModel(
            Config.STT_MODEL_SIZE,
            device="cpu",
            compute_type=Config.STT_COMPUTE_TYPE,
            cpu_threads=Config.STT_THREADS,
            download_root=Config.STT_MODEL_DIR,
        )
        logger.info("Модель распознавания речи %s загружена", Config.STT_MODEL_SIZE)
        return _model


def warm_up() -> None:
    try:
        _load()
    except Exception as exc:  # модель могла не скачаться заранее
        logger.warning("Прогрев STT не удался: %s", exc)


def transcribe(path: str) -> str:
    """Возвращает распознанный текст (может быть пустой строкой - тишина)."""
    model = _load()
    try:
        segments, _info = model.transcribe(
            path,
            language=Config.STT_LANGUAGE,
            beam_size=Config.STT_BEAM_SIZE,
            vad_filter=True,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()
    except Exception as exc:
        raise SttError(f"Не удалось распознать запись: {exc}") from exc
