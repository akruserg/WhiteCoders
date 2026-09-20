import os


def _bool(name, default="0"):
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return int(default)


def _required(name):
    value = os.environ.get(name)

    if value is None or not value.strip():
        raise RuntimeError(f"Required environment variable {name!r} is not set")

    return value.strip()


class Config:
    SECRET_KEY = _required("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = _required("DATABASE_URL")

    # database

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_size": _int("DB_POOL_SIZE", 20),
        "max_overflow": _int("DB_MAX_OVERFLOW", 20),
        "pool_pre_ping": True,
        "pool_recycle": 1800,
    }

    # JWT ; authentication

    JWT_ALGORITHM = "HS256"
    JWT_ISSUER = os.environ.get("JWT_ISSUER", "arm112-trainer")

    ACCESS_TOKEN_TTL_SEC = _int("ACCESS_TOKEN_TTL_SEC", 900)
    REFRESH_TOKEN_TTL_SEC = _int("REFRESH_TOKEN_TTL_SEC", 43200)
    MFA_TOKEN_TTL_SEC = _int("MFA_TOKEN_TTL_SEC", 300)
    MAX_FAILED_LOGINS = _int("MAX_FAILED_LOGINS", 5)

    # training
    DEFAULT_TIME_LIMIT_SEC = _int("DEFAULT_TIME_LIMIT_SEC", 30)
    DEFAULT_PASS_SCORE = float(os.environ.get("DEFAULT_PASS_SCORE", 70))
    AUDIT_RETENTION_DAYS = _int("AUDIT_RETENTION_DAYS", 190)

    # pagination ; uploads

    MAX_PAGE_SIZE = _int("MAX_PAGE_SIZE", 200)
    DEFAULT_PAGE_SIZE = _int("DEFAULT_PAGE_SIZE", 50)
    MAX_CONTENT_LENGTH = _int("MAX_UPLOAD_MB", 64) * 1024 * 1024

    # storage

    MATERIALS_DIR = os.environ.get(
        "MATERIALS_DIR",
        "/var/lib/arm112/materials",
    )

    REPORTS_DIR = os.environ.get(
        "REPORTS_DIR",
        "/var/lib/arm112/reports",
    )

    BACKUPS_DIR = os.environ.get(
        "BACKUPS_DIR",
        "/var/lib/arm112/backups",
    )
    BACKUP_HOUR_UTC = _int("BACKUP_HOUR_UTC", 3)
    BACKUPS_KEEP = _int("BACKUPS_KEEP", 30)

    # VoIP

    VOIP_ENABLED = _bool("VOIP_ENABLED", "0")

    VOIP_DESTINATION = os.environ.get(
        "VOIP_DESTINATION",
        "",
    ).strip()

    VOIP_MAX_LATENCY_MS = _int(
        "VOIP_MAX_LATENCY_MS",
        150,
    )

    ARM_VOIP_BASE_URL = os.environ.get(
        "ARM_VOIP_BASE_URL",
        "http://arm_voip:8001",
    ).strip()

    ARM_VOIP_TIMEOUT_SEC = float(
        os.environ.get(
            "ARM_VOIP_TIMEOUT_SEC",
            "5",
        )
    )

    ARM_VOIP_SERVICE_TOKEN = (
        _required("ARM_VOIP_SERVICE_TOKEN")
        if VOIP_ENABLED
        else os.environ.get(
            "ARM_VOIP_SERVICE_TOKEN",
            "",
        )
    )

    # AI: локальная модель YandexGPT-5-Lite-8B-instruct за сервером llama.cpp

    AI_ENABLED = _bool("AI_ENABLED", "0")
    AI_SCORING_ENABLED = _bool("AI_SCORING_ENABLED", "0")
    AI_BASE_URL = os.environ.get("AI_BASE_URL", "http://llm:8080").strip().rstrip("/")
    AI_MODEL_NAME = os.environ.get(
        "AI_MODEL_NAME", "YandexGPT-5-Lite-8B-instruct-Q4_K_M"
    ).strip()
    AI_TIMEOUT_SEC = float(os.environ.get("AI_TIMEOUT_SEC", "240"))
    AI_JUDGE_TIMEOUT_SEC = float(os.environ.get("AI_JUDGE_TIMEOUT_SEC", "20"))
    AI_MAX_TOKENS = _int("AI_MAX_TOKENS", 1500)
    AI_TEMPERATURE = float(os.environ.get("AI_TEMPERATURE", "0.5"))
    AI_MAX_SCENARIOS_PER_REQUEST = _int("AI_MAX_SCENARIOS_PER_REQUEST", 5)

    # CORS

    CORS_ORIGINS = [
        origin.strip()
        for origin in _required("CORS_ORIGINS").split(",")
        if origin.strip()
    ]

    # logging: json (по ТЗ) или text для отладки
    LOG_FORMAT = os.environ.get("LOG_FORMAT", "json").strip().lower()
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").strip().upper()

    # api

    API_PREFIX = os.environ.get("API_PREFIX", "/api/v1")
