import os


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, str(default)))


def _bool(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


class Config:
    """Настройки голосового модуля. Работает полностью офлайн: модели читаются
    с локального диска, наружу (в интернет) сервис не обращается."""

    SERVICE_TOKEN = os.environ.get("VOICE_SERVICE_TOKEN", "")

    # -- TTS (Piper, ONNX, CPU) -----------------------------------------------
    TTS_VOICES_DIR = os.environ.get("TTS_VOICES_DIR", "/models/piper")
    # имя без расширения: ищутся <TTS_VOICES_DIR>/<voice>.onnx и .onnx.json
    TTS_DEFAULT_VOICE = os.environ.get("TTS_DEFAULT_VOICE", "ru_RU-irina-medium")
    TTS_MAX_CHARS = _int("TTS_MAX_CHARS", 600)

    # -- STT (faster-whisper, CTranslate2, CPU) -------------------------------
    STT_MODEL_DIR = os.environ.get("STT_MODEL_DIR", "/models/whisper")
    # tiny/base/small/medium: чем крупнее, тем точнее и медленнее на CPU
    STT_MODEL_SIZE = os.environ.get("STT_MODEL_SIZE", "small")
    STT_LANGUAGE = os.environ.get("STT_LANGUAGE", "ru")
    STT_COMPUTE_TYPE = os.environ.get("STT_COMPUTE_TYPE", "int8")
    STT_BEAM_SIZE = _int("STT_BEAM_SIZE", 1)
    STT_THREADS = _int("STT_THREADS", 4)

    WARM_UP = _bool("VOICE_WARM_UP", "1")

    @classmethod
    def problems(cls) -> list[str]:
        found = []
        if not cls.SERVICE_TOKEN:
            found.append("VOICE_SERVICE_TOKEN не задан")
        return found
