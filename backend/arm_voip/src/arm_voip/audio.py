import logging
import os
import re
import shutil
import subprocess

from .config import Config

logger = logging.getLogger(__name__)

_SAFE_NAME = re.compile(r"^[\w.\-]{1,128}$")
_SOURCE_EXTENSIONS = (".wav", ".mp3")


def _normalized_name(stem: str) -> str:
    return f"{stem}_pbx"


def _convert(source: str, target: str) -> bool:
    """Приводит запись к формату телефонии: WAV, 8 кГц, моно, 16 бит."""
    if shutil.which("ffmpeg") is None:
        return False
    tmp = target + ".part.wav"
    command = [
        "ffmpeg", "-y", "-loglevel", "error", "-i", source,
        "-ar", "8000", "-ac", "1", "-c:a", "pcm_s16le", tmp,
    ]  # fmt: skip
    completed = subprocess.run(command, capture_output=True, timeout=120, check=False)
    if completed.returncode != 0:
        logger.warning(
            "ffmpeg не смог обработать %s: %s", source, completed.stderr[:300]
        )
        return False
    os.replace(tmp, target)
    return True


def resolve_media(name: str | None) -> str | None:
    """Имя записи из сценария -> идентификатор media для Asterisk.

    Ищет <AUDIO_DIR>/<имя>.wav или .mp3, при возможности приводит к формату
    телефонии. Возвращает None, если записи нет: звонок пройдет без звука.
    """
    if not name:
        return None

    stem, _ = os.path.splitext(name)
    if not _SAFE_NAME.match(stem) or stem.startswith("."):
        logger.warning("Недопустимое имя аудиозаписи: %r", name)
        return None

    directory = Config.AUDIO_DIR
    normalized = os.path.join(directory, _normalized_name(stem) + ".wav")
    if os.path.exists(normalized):
        return f"sound:{Config.AUDIO_SOUND_PREFIX}/{_normalized_name(stem)}"

    for extension in _SOURCE_EXTENSIONS:
        source = os.path.join(directory, stem + extension)
        if not os.path.exists(source):
            continue
        if _convert(source, normalized):
            return f"sound:{Config.AUDIO_SOUND_PREFIX}/{_normalized_name(stem)}"
        if extension == ".wav":
            # ffmpeg недоступен: играем как есть, файл должен быть 8 кГц моно
            return f"sound:{Config.AUDIO_SOUND_PREFIX}/{stem}"
        logger.warning("Для %s нужен ffmpeg, MP3 воспроизвести нельзя", source)

    logger.warning("Аудиозапись %r не найдена в %s", name, directory)
    return None
