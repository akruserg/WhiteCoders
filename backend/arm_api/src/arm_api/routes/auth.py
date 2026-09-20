"""
POST /auth/login     - первый фактор (логин/пароль)
POST /auth/mfa       - второй фактор (TOTP), если включен
POST /auth/refresh   - обновление пары токенов (ротация refresh)
POST /auth/logout    - отзыв refresh-токена
GET  /auth/me        - профиль, роль и права текущего пользователя
POST /auth/password  - смена собственного пароля
"""

import uuid
from datetime import datetime, timezone

from flask import Blueprint, current_app, request
from sqlalchemy import select

from ..core.errors import ApiError
from ..core.extensions import db
from ..core.security import (
    check_password_policy,
    current_user,
    decode_token,
    find_refresh_token,
    hash_password,
    issue_access_token,
    issue_mfa_token,
    issue_refresh_token,
    user_permissions,
    verify_password,
    verify_totp,
    write_audit,
)
from ..models import User
from ..services import settings
from ..schemas import LoginIn, MfaIn, PasswordChangeIn, RefreshIn
from ._helpers import body, commit, ok

auth_bp = Blueprint("auth", __name__)


def _max_failed_logins():
    return int(
        settings.get(
            "security.max_failed_logins", current_app.config["MAX_FAILED_LOGINS"]
        )
    )


def _profile(user):
    return {
        **user.to_dict(),
        "role": user.role.to_dict(),
        "permissions": sorted(user_permissions(user)),
        "service_scope": [category.to_dict() for category in user.service_scope],
        "groups": [{"id": str(g.id), "name": g.name} for g in user.groups],
    }


def _token_pair(user):
    access, expires_in = issue_access_token(user)
    raw_refresh, _ = issue_refresh_token(
        user,
        user_agent=request.headers.get("User-Agent"),
        ip=request.headers.get("X-Real-IP") or request.remote_addr,
    )
    user.last_login_at = datetime.now(timezone.utc)
    user.failed_attempts = 0
    return {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": expires_in,
        "refresh_token": raw_refresh,
        "user": _profile(user),
    }


@auth_bp.post("/auth/login")
def login():
    payload = body(LoginIn)
    user = (
        db.session.execute(select(User).where(User.username == payload.username))
        .scalars()
        .first()
    )

    if user is None or not verify_password(user.password_hash, payload.password):
        if user is not None:
            user.failed_attempts = (user.failed_attempts or 0) + 1
            if user.failed_attempts >= _max_failed_logins():
                user.is_blocked = True
            write_audit(
                db.session,
                request,
                user,
                "auth.login_failed",
                "user",
                user.id,
                {"failed_attempts": user.failed_attempts},
            )
            commit()
        raise ApiError("Неверный логин или пароль", 401, code="invalid_credentials")

    if not user.is_active:
        raise ApiError("Учетная запись отключена", 403, code="user_inactive")
    if user.is_blocked:
        raise ApiError(
            "Учетная запись заблокирована, обратитесь к администратору",
            403,
            code="user_blocked",
        )

    if user.mfa_enabled:
        write_audit(db.session, request, user, "auth.mfa_required", "user", user.id)
        commit()
        return ok(
            {
                "mfa_required": True,
                "mfa_token": issue_mfa_token(user),
                "expires_in": current_app.config["MFA_TOKEN_TTL_SEC"],
            }
        )

    tokens = _token_pair(user)
    write_audit(db.session, request, user, "auth.login", "user", user.id)
    commit()
    return ok(tokens)


@auth_bp.post("/auth/mfa")
def mfa():
    payload = body(MfaIn)
    claims = decode_token(payload.mfa_token, "mfa")
    user = db.session.get(User, uuid.UUID(claims["sub"]))
    if user is None or not user.is_active or user.is_blocked:
        raise ApiError("Учетная запись недоступна", 403)

    if not verify_totp(user.mfa_secret, payload.code):
        user.failed_attempts = (user.failed_attempts or 0) + 1
        if user.failed_attempts >= _max_failed_logins():
            user.is_blocked = True
        write_audit(db.session, request, user, "auth.mfa_failed", "user", user.id)
        commit()
        raise ApiError("Неверный код подтверждения", 401, code="invalid_mfa_code")

    tokens = _token_pair(user)
    write_audit(db.session, request, user, "auth.login", "user", user.id, {"mfa": True})
    commit()
    return ok(tokens)


@auth_bp.post("/auth/refresh")
def refresh():
    payload = body(RefreshIn)
    record = find_refresh_token(payload.refresh_token)
    user = db.session.get(User, record.user_id)
    if user is None or not user.is_active or user.is_blocked:
        raise ApiError("Учетная запись недоступна", 403)

    record.revoked_at = datetime.now(timezone.utc)
    tokens = _token_pair(user)
    write_audit(db.session, request, user, "auth.refresh", "user", user.id)
    commit()
    return ok(tokens)


@auth_bp.post("/auth/logout")
def logout():
    payload = body(RefreshIn)
    record = find_refresh_token(payload.refresh_token)
    record.revoked_at = datetime.now(timezone.utc)
    user = db.session.get(User, record.user_id)
    write_audit(db.session, request, user, "auth.logout", "user", record.user_id)
    commit()
    return ok({"status": "ok"})


@auth_bp.get("/auth/me")
def me():
    return ok(_profile(current_user()))


@auth_bp.post("/auth/password")
def change_password():
    user = current_user()
    payload = body(PasswordChangeIn)
    if not verify_password(user.password_hash, payload.old_password):
        raise ApiError("Текущий пароль указан неверно", 403)
    check_password_policy(payload.new_password)

    user.password_hash = hash_password(payload.new_password)
    user.password_changed_at = datetime.now(timezone.utc)
    for token in user.refresh_tokens:
        if token.revoked_at is None:
            token.revoked_at = datetime.now(timezone.utc)
    write_audit(db.session, request, user, "auth.password_change", "user", user.id)
    commit()
    return ok({"status": "ok"})
