import os


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name, str(default)))


def _bool(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _ari_ws_url(base_url: str) -> str:
    # http://asterisk:8088/ari -> ws://asterisk:8088/ari/events
    scheme = "wss" if base_url.startswith("https") else "ws"
    return f"{scheme}://{base_url.split('://', 1)[-1].rstrip('/')}/events"


class Config:
    """Настройки сервиса. Все значения берутся из окружения (см. .env_example)."""

    # ARI (управление Asterisk)
    ARI_BASE_URL = os.environ.get("ARI_BASE_URL", "http://asterisk:8088/ari")
    ARI_USERNAME = os.environ.get("ARI_USERNAME", "arm_voip")
    ARI_PASSWORD = os.environ.get("ARI_PASSWORD", "")
    ARI_APP_NAME = os.environ.get("ARI_APP_NAME", "arm_voip")
    ARI_TIMEOUT_SEC = _float("ARI_TIMEOUT_SEC", 5)
    ARI_WS_URL = os.environ.get("ARI_WS_URL") or _ari_ws_url(ARI_BASE_URL)

    # доступ к сервису и обратная связь с arm_api
    SERVICE_TOKEN = os.environ.get("ARM_VOIP_SERVICE_TOKEN", "")
    ARM_API_URL = os.environ.get("ARM_API_URL", "http://arm_api:5000/api/v1").rstrip(
        "/"
    )
    ARM_API_TIMEOUT_SEC = _float("ARM_API_TIMEOUT_SEC", 5)

    # пул SIP-номеров операторов: по одному номеру на одновременный звонок
    VOIP_POOL_SIZE = _int("VOIP_POOL_SIZE", 20)
    VOIP_POOL_START = _int("VOIP_POOL_START", 2001)
    VOIP_LEASE_TTL_SEC = _int("VOIP_LEASE_TTL_SEC", 900)
    VOIP_SIP_SECRET = os.environ.get("VOIP_SIP_SECRET", "")
    # webrtc - браузерный софтфон (SIP.js/JsSIP), sip - обычный IP-телефон по UDP
    VOIP_ENDPOINT_MODE = os.environ.get("VOIP_ENDPOINT_MODE", "webrtc")
    # то, что получает браузер для регистрации софтфона
    SIP_WS_URL = os.environ.get("SIP_WS_URL", "ws://localhost:8088/ws")
    SIP_DOMAIN = os.environ.get("SIP_DOMAIN", "localhost")

    # необязательный фиксированный номер (стенд с одним аппаратом): в обход пула
    VOIP_DESTINATION = os.environ.get("VOIP_DESTINATION", "").strip()
    VOIP_DIALPLAN_CONTEXT = os.environ.get("VOIP_DIALPLAN_CONTEXT", "arm112")
    VOIP_RING_TIMEOUT_SEC = _int("VOIP_RING_TIMEOUT_SEC", 30)
    VOIP_MAX_CALL_SEC = _int("VOIP_MAX_CALL_SEC", 900)

    # требования ТЗ: задержка передачи голоса не более 150 мс
    VOIP_MAX_LATENCY_MS = _int("VOIP_MAX_LATENCY_MS", 150)
    VOIP_RTT_POLL_SEC = _float("VOIP_RTT_POLL_SEC", 5)

    # звук учебных вызовов (WAV/MP3) и сгенерированный конфиг Asterisk
    AUDIO_DIR = os.environ.get("AUDIO_DIR", "/audio")
    AUDIO_SOUND_PREFIX = os.environ.get("AUDIO_SOUND_PREFIX", "arm112")
    GENERATED_DIR = os.environ.get("GENERATED_DIR", "/generated")

    # голосовой диалог: живой звонок оператора с ИИ-заявителем
    # (речь оператора -> распознавание -> нейросеть -> синтез -> назад в VoIP)
    VOICE_DIALOG_ENABLED = _bool("VOICE_DIALOG_ENABLED", "0")
    VOICE_BASE_URL = os.environ.get("VOICE_BASE_URL", "http://voice:8090").rstrip("/")
    VOICE_SERVICE_TOKEN = os.environ.get("VOICE_SERVICE_TOKEN", "")
    VOICE_TTS_TIMEOUT_SEC = _float("VOICE_TTS_TIMEOUT_SEC", 20)
    VOICE_STT_TIMEOUT_SEC = _float("VOICE_STT_TIMEOUT_SEC", 20)
    TTS_DEFAULT_VOICE = os.environ.get("TTS_DEFAULT_VOICE", "ru_RU-irina-medium")

    # запись реплики оператора: каталог, куда Asterisk кладет файлы ARI record
    RECORDING_DIR = os.environ.get("RECORDING_DIR", "/recordings")
    RECORDING_FORMAT = os.environ.get("RECORDING_FORMAT", "wav")
    # диалог обрывается после стольких реплик оператора (карточку можно
    # дозаполнить и без диалога - это не блокирует занятие)
    VOICE_DIALOG_MAX_TURNS = _int("VOICE_DIALOG_MAX_TURNS", 6)
    # запись реплики оператора останавливается по паузе или по таймауту
    VOICE_MAX_SILENCE_SEC = _int("VOICE_MAX_SILENCE_SEC", 2)
    VOICE_MAX_UTTERANCE_SEC = _int("VOICE_MAX_UTTERANCE_SEC", 20)

    @classmethod
    def problems(cls) -> list[str]:
        """Что мешает запуску. Пустой список - конфигурация пригодна."""
        found = []
        if not cls.SERVICE_TOKEN:
            found.append("ARM_VOIP_SERVICE_TOKEN не задан")
        if not cls.ARI_PASSWORD:
            found.append("ARI_PASSWORD не задан")
        if not cls.VOIP_DESTINATION and not cls.VOIP_SIP_SECRET:
            found.append("VOIP_SIP_SECRET не задан (нужен для паролей SIP-номеров)")
        if cls.VOIP_ENDPOINT_MODE not in {"webrtc", "sip"}:
            found.append("VOIP_ENDPOINT_MODE должен быть webrtc или sip")
        if cls.VOIP_POOL_SIZE < 1:
            found.append("VOIP_POOL_SIZE должен быть не меньше 1")
        if cls.VOICE_DIALOG_ENABLED and not cls.VOICE_SERVICE_TOKEN:
            found.append(
                "VOICE_SERVICE_TOKEN не задан (нужен для VOICE_DIALOG_ENABLED)"
            )
        return found
