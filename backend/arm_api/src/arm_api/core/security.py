import base64
import hashlib
import hmac
import secrets
import struct
import time
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from flask import current_app, g, request
from sqlalchemy import text
from werkzeug.security import check_password_hash, generate_password_hash

from .errors import ApiError
from .extensions import db

PERMISSIONS = {
    "user.manage": "Управление учетными записями и ролями",
    "system.manage": "Управление сервисами, настройками и резервным копированием",
    "system.monitor": "Просмотр журналов, метрик и состояния компонентов",
    "audit.read": "Просмотр журнала аудита",
    "catalog.manage": "Управление справочниками (категории, шаблоны, профили оценки)",
    "scenario.read": "Просмотр учебных сценариев",
    "scenario.manage": "Создание и редактирование сценариев",
    "scenario.validate": "Утверждение (валидация) сценариев",
    "material.manage": "Загрузка методических материалов",
    "session.manage": "Проведение занятий",
    "session.participate": "Участие в занятии в роли обучающегося",
    "attempt.submit": "Отправка заполненной карточки",
    "attempt.grade": "Экспертная оценка карточек",
    "report.create": "Формирование отчетов",
    "report.read.any": "Просмотр отчетов и результатов любых обучающихся",
    "insight.manage": "Работа с аналитикой и рекомендациями ИИ",
    "certificate.issue": "Выдача сертификатов",
}

ROLE_PERMISSIONS = {
    "admin": [
        "user.manage",
        "system.manage",
        "system.monitor",
        "audit.read",
        "catalog.manage",
        "scenario.read",
        "report.create",  # только системные отчеты, см. ADMIN_REPORT_KINDS
    ],
    "teacher": [
        "scenario.read",
        "scenario.manage",
        "scenario.validate",
        "material.manage",
        "catalog.manage",
        "session.manage",
        "attempt.grade",
        "report.create",
        "report.read.any",
        "insight.manage",
        "certificate.issue",
        "system.monitor",
    ],
    "student": [
        "session.participate",
        "attempt.submit",
        "scenario.read",
    ],
}


# Администратору доступны только отчеты о системе: результаты обучающихся
# (персональные данные) он видеть без необходимости не должен
ADMIN_REPORT_KINDS = {"system_usage", "security_audit"}


def hash_password(password):
    return generate_password_hash(password, method="pbkdf2:sha256:600000")


def verify_password(password_hash, password):
    return check_password_hash(password_hash, password)


def check_password_policy(password):
    problems = []
    if len(password or "") < 10:
        problems.append("не менее 10 символов")
    if not any(ch.isdigit() for ch in password or ""):
        problems.append("хотя бы одна цифра")
    if not any(ch.isalpha() for ch in password or ""):
        problems.append("хотя бы одна буква")
    if problems:
        raise ApiError(
            "Пароль не соответствует политике: " + ", ".join(problems),
            422,
            code="weak_password",
        )


def generate_mfa_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _totp(secret, counter):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{code % 1_000_000:06d}"


def verify_totp(secret, code, window=1):
    if not secret or not code:
        return False
    counter = int(time.time()) // 30
    return any(
        hmac.compare_digest(_totp(secret, counter + shift), str(code).strip())
        for shift in range(-window, window + 1)
    )


def _now():
    return datetime.now(timezone.utc)


def issue_access_token(user):
    cfg = current_app.config
    permissions = sorted(p.code for p in user.role.permissions)
    payload = {
        "iss": cfg["JWT_ISSUER"],
        "sub": str(user.id),
        "typ": "access",
        "username": user.username,
        "role": user.role.code,
        "perms": permissions,
        "jti": uuid.uuid4().hex,
        "iat": int(_now().timestamp()),
        "exp": int(
            (_now() + timedelta(seconds=cfg["ACCESS_TOKEN_TTL_SEC"])).timestamp()
        ),
    }
    token = jwt.encode(payload, cfg["SECRET_KEY"], algorithm=cfg["JWT_ALGORITHM"])
    return token, cfg["ACCESS_TOKEN_TTL_SEC"]


def issue_mfa_token(user):
    cfg = current_app.config
    payload = {
        "iss": cfg["JWT_ISSUER"],
        "sub": str(user.id),
        "typ": "mfa",
        "iat": int(_now().timestamp()),
        "exp": int((_now() + timedelta(seconds=cfg["MFA_TOKEN_TTL_SEC"])).timestamp()),
    }
    return jwt.encode(payload, cfg["SECRET_KEY"], algorithm=cfg["JWT_ALGORITHM"])


def decode_token(token, expected_type="access"):
    cfg = current_app.config
    try:
        payload = jwt.decode(
            token,
            cfg["SECRET_KEY"],
            algorithms=[cfg["JWT_ALGORITHM"]],
            issuer=cfg["JWT_ISSUER"],
        )
    except jwt.ExpiredSignatureError:
        raise ApiError("Срок действия токена истек", 401, code="token_expired")
    except jwt.InvalidTokenError:
        raise ApiError("Некорректный токен", 401, code="invalid_token")
    if payload.get("typ") != expected_type:
        raise ApiError("Неподходящий тип токена", 401, code="invalid_token")
    return payload


def issue_refresh_token(user, user_agent=None, ip=None):
    from ..models import RefreshToken

    raw = secrets.token_urlsafe(48)
    record = RefreshToken(
        user_id=user.id,
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        expires_at=_now()
        + timedelta(seconds=current_app.config["REFRESH_TOKEN_TTL_SEC"]),
        user_agent=(user_agent or "")[:255] or None,
        ip=(ip or "")[:64] or None,
    )
    db.session.add(record)
    return raw, record


def find_refresh_token(raw):
    from ..models import RefreshToken
    from sqlalchemy import select

    token_hash = hashlib.sha256((raw or "").encode()).hexdigest()
    record = (
        db.session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        .scalars()
        .first()
    )
    if record is None or record.revoked_at is not None:
        raise ApiError("Refresh-токен недействителен", 401, code="invalid_token")
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < _now():
        raise ApiError("Срок действия refresh-токена истек", 401, code="token_expired")
    return record


_PUBLIC_PATHS = {
    "/",
    "/health",
    "/auth/login",
    "/auth/mfa",
    "/auth/refresh",
    "/auth/logout",
    "/openapi.json",
    "/internal/voip/events",  # закрыт служебным токеном, а не JWT
}


def _normalize_path(path):
    if not path or path == "/":
        return "/"
    return path.rstrip("/") or "/"


def is_public_path(path, api_prefix="/api/v1"):
    normalized = _normalize_path(path)
    prefix = _normalize_path(api_prefix)
    under_api = prefix != "/" and (
        normalized == prefix or normalized.startswith(prefix + "/")
    )
    if under_api:
        rest = normalized[len(prefix) :] or "/"
        return rest in _PUBLIC_PATHS
    return normalized in _PUBLIC_PATHS


def authenticate_protected_request():
    if request.method == "OPTIONS":
        return
    prefix = current_app.config.get("API_PREFIX", "/api/v1")
    if is_public_path(request.path, prefix):
        return
    current_user()


def _bearer_token():
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        raise ApiError("Требуется авторизация", 401, code="unauthenticated")
    return header.split(None, 1)[1].strip()


def current_user():
    from ..models import User

    if getattr(g, "current_user", None) is not None:
        return g.current_user

    payload = decode_token(_bearer_token(), "access")
    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        raise ApiError("Некорректный токен", 401, code="invalid_token")

    user = db.session.get(User, user_id)
    if user is None or not user.is_active:
        raise ApiError("Учетная запись недоступна", 401, code="unauthenticated")
    if user.is_blocked:
        raise ApiError("Учетная запись заблокирована", 403, code="user_blocked")

    g.current_user = user
    g.token_payload = payload
    return user


def user_permissions(user):
    return {p.code for p in user.role.permissions}


def require(*permissions):
    user = current_user()
    granted = user_permissions(user)
    if permissions and not granted.intersection(permissions):
        raise ApiError(
            "Недостаточно прав для операции",
            403,
            code="forbidden",
            details={"required_any": list(permissions)},
        )
    return user


def require_role(*role_codes):
    user = current_user()
    if user.role.code not in role_codes:
        raise ApiError("Операция недоступна для вашей роли", 403)
    return user


def is_admin(user):
    return user.role.code == "admin"


def is_teacher(user):
    return user.role.code == "teacher"


def is_student(user):
    return user.role.code == "student"


AUDIT_LOCK_KEY = 112001  # ключ advisory-lock: записи журнала строятся в цепочку


def _entry_hash(prev_hash, parts):
    payload = "|".join([prev_hash or ""] + [str(p) for p in parts])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def audit_entry_hash(entry):
    """Хэш записи по ее содержимому. Им же журнал проверяется на подделку."""
    ts = entry.ts.astimezone(timezone.utc).isoformat()
    return _entry_hash(
        entry.prev_hash,
        [ts, entry.user_id, entry.action, entry.object_type, entry.object_id],
    )


def write_audit(
    session, req, user, action, object_type=None, object_id=None, payload=None
):
    from sqlalchemy import select

    from ..models import AuditLog

    # Без блокировки два воркера читают один и тот же prev_hash и цепочка
    # раздваивается. Блокировка снимается вместе с транзакцией.
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": AUDIT_LOCK_KEY})
    prev_hash = session.execute(
        select(AuditLog.entry_hash).order_by(AuditLog.id.desc()).limit(1)
    ).scalar()

    ts = _now()
    entry = AuditLog(
        ts=ts,
        user_id=getattr(user, "id", None),
        role_code=getattr(getattr(user, "role", None), "code", None),
        action=action,
        object_type=object_type,
        object_id=str(object_id) if object_id is not None else None,
        ip=(req.headers.get("X-Real-IP") or req.remote_addr or "")[:64] or None,
        user_agent=(req.headers.get("User-Agent") or "")[:255] or None,
        payload=payload or {},
        prev_hash=prev_hash,
    )
    entry.entry_hash = audit_entry_hash(entry)
    session.add(entry)
    return entry


def log_event(component, level, message, details=None):
    from ..models import SystemEvent

    db.session.add(
        SystemEvent(
            component=component,
            level=level,
            message=message,
            details=details or {},
        )
    )
