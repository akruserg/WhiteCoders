"""
GET    /users                     - список с фильтрами (роль, активность, поиск)
POST   /users                     - создание учетной записи
GET    /users/{id}                - карточка пользователя
PATCH  /users/{id}                - изменение профиля, роли, профиля событий
POST   /users/{id}/block          - блокировка
POST   /users/{id}/unblock        - разблокировка
POST   /users/{id}/reset-password - сброс пароля администратором
GET    /roles, GET /permissions   - справочники RBAC
GET    /roles/matrix              - матрица прав: роли x права, с обязательными и запрещенными
PUT    /roles/{code}/permissions  - заменить набор прав роли (с проверкой ограничений ТЗ)
POST   /roles/{code}/permissions/reset - вернуть права роли по умолчанию
CRUD   /groups                    - учебные группы и их состав
"""

import uuid
from datetime import datetime, timezone

from flask import Blueprint, request
from sqlalchemy import or_, select

from ..core.errors import ApiError
from ..core.extensions import db
from ..core.pagination import paginate
from ..core.security import (
    PERMISSIONS,
    ROLE_FORBIDDEN,
    ROLE_MUST_HAVE,
    ROLE_PERMISSIONS,
    check_password_policy,
    check_role_permissions,
    current_user,
    generate_mfa_secret,
    hash_password,
    is_admin,
    require,
    write_audit,
)
from ..models import Group, IncidentCategory, Permission, Role, User
from ..schemas import (
    GroupIn,
    MembersIn,
    PasswordResetIn,
    RolePermissionsIn,
    UserCreate,
    UserUpdate,
)
from ..services.backup import require_recent_backup
from ._helpers import body, commit, get_or_404, item, items, ok, uuid_arg

users_bp = Blueprint("users", __name__)


def _role_by_code(code):
    role = db.session.execute(select(Role).where(Role.code == code)).scalars().first()
    if role is None:
        raise ApiError(f"Роль «{code}» не найдена", 422)
    return role


def _set_scope(user, category_ids):
    if category_ids is None:
        return
    categories = (
        list(
            db.session.execute(
                select(IncidentCategory).where(IncidentCategory.id.in_(category_ids))
            ).scalars()
        )
        if category_ids
        else []
    )
    missing = set(category_ids) - {c.id for c in categories}
    if missing:
        raise ApiError(f"Неизвестные категории: {sorted(missing)}", 422)
    user.service_scope = categories


def _user_view(user):
    return {
        **user.to_dict(),
        "role_code": user.role.code if user.role else None,
        "category_ids": [c.id for c in user.service_scope],
        "group_ids": [str(g.id) for g in user.groups],
    }


@users_bp.get("/users")
def list_users():
    principal = require("user.manage", "session.manage")
    stmt = select(User).join(Role, Role.id == User.role_id)
    if not is_admin(principal):  # преподаватель видит только обучающихся
        stmt = stmt.where(Role.code == "student")

    role_code = request.args.get("role")
    if role_code:
        stmt = stmt.where(Role.code == role_code)
    if request.args.get("is_active") is not None:
        flag = request.args.get("is_active").lower() in {"1", "true", "yes"}
        stmt = stmt.where(User.is_active.is_(flag))
    if request.args.get("is_blocked") is not None:
        flag = request.args.get("is_blocked").lower() in {"1", "true", "yes"}
        stmt = stmt.where(User.is_blocked.is_(flag))
    search = request.args.get("q")
    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(User.full_name.ilike(pattern), User.username.ilike(pattern))
        )
    group_id = uuid_arg("group_id")
    if group_id:
        group = get_or_404(Group, group_id, "Группа")
        stmt = stmt.where(User.id.in_([m.id for m in group.members] or [None]))

    return ok(paginate(stmt.order_by(User.full_name), serializer=_user_view))


@users_bp.post("/users")
def create_user():
    principal = require("user.manage")
    payload = body(UserCreate)
    check_password_policy(payload.password)

    exists = db.session.execute(
        select(User.id).where(User.username == payload.username)
    ).first()
    if exists:
        raise ApiError("Пользователь с таким логином уже существует", 409)

    user = User(
        username=payload.username,
        full_name=payload.full_name,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role_id=_role_by_code(payload.role_code).id,
        mfa_enabled=bool(payload.mfa_enabled),
    )
    if payload.mfa_enabled:
        user.mfa_secret = generate_mfa_secret()
    db.session.add(user)
    db.session.flush()
    _set_scope(user, payload.category_ids)

    write_audit(
        db.session,
        request,
        principal,
        "user.create",
        "user",
        user.id,
        {"role": payload.role_code},
    )
    commit()

    response = _user_view(user)
    if user.mfa_enabled:
        response["mfa_secret"] = user.mfa_secret
        response["mfa_uri"] = (
            f"otpauth://totp/ARM-112:{user.username}?secret={user.mfa_secret}"
            f"&issuer=ARM-112"
        )
    return ok(response, 201)


@users_bp.get("/users/<uuid:user_id>")
def get_user(user_id):
    principal = require("user.manage", "session.manage", "report.read.any")
    user = get_or_404(User, user_id, "Пользователь")
    if (
        not is_admin(principal)
        and user.id != principal.id
        and user.role.code != "student"
    ):
        raise ApiError("Доступны только карточки обучающихся", 403)
    return ok(_user_view(user))


@users_bp.patch("/users/<uuid:user_id>")
def update_user(user_id):
    principal = require("user.manage")
    user = get_or_404(User, user_id, "Пользователь")
    payload = body(UserUpdate)

    if user.id == principal.id and (
        payload.is_active is False
        or (payload.role_code and payload.role_code != user.role.code)
    ):
        raise ApiError("Нельзя отключить или понизить собственную учетную запись", 409)

    changed = {}
    for name in ("full_name", "email", "is_active", "mfa_enabled"):
        value = getattr(payload, name, None)
        if value is not None:
            setattr(user, name, value)
            changed[name] = value
    if payload.role_code:
        user.role_id = _role_by_code(payload.role_code).id
        changed["role_code"] = payload.role_code
    new_secret = None
    if payload.mfa_enabled and not user.mfa_secret:
        new_secret = user.mfa_secret = generate_mfa_secret()
    if payload.category_ids is not None:
        _set_scope(user, payload.category_ids)
        changed["category_ids"] = payload.category_ids

    write_audit(db.session, request, principal, "user.update", "user", user.id, changed)
    commit()
    response = _user_view(user)
    if new_secret:  # без выдачи секрета включенный MFA заблокировал бы вход
        response["mfa_secret"] = new_secret
        response["mfa_uri"] = (
            f"otpauth://totp/ARM-112:{user.username}?secret={new_secret}"
            f"&issuer=ARM-112"
        )
    return ok(response)


@users_bp.post("/users/<uuid:user_id>/block")
def block_user(user_id):
    principal = require("user.manage")
    user = get_or_404(User, user_id, "Пользователь")
    if user.id == principal.id:
        raise ApiError("Нельзя заблокировать собственную учетную запись", 409)
    user.is_blocked = True
    for token in user.refresh_tokens:
        if token.revoked_at is None:
            token.revoked_at = datetime.now(timezone.utc)
    write_audit(db.session, request, principal, "user.block", "user", user.id)
    commit()
    return ok(_user_view(user))


@users_bp.post("/users/<uuid:user_id>/unblock")
def unblock_user(user_id):
    principal = require("user.manage")
    user = get_or_404(User, user_id, "Пользователь")
    user.is_blocked = False
    user.failed_attempts = 0
    write_audit(db.session, request, principal, "user.unblock", "user", user.id)
    commit()
    return ok(_user_view(user))


@users_bp.post("/users/<uuid:user_id>/reset-password")
def reset_password(user_id):
    principal = require("user.manage")
    user = get_or_404(User, user_id, "Пользователь")
    payload = body(PasswordResetIn)
    check_password_policy(payload.new_password)

    user.password_hash = hash_password(payload.new_password)
    user.password_changed_at = datetime.now(timezone.utc)
    user.failed_attempts = 0
    for token in user.refresh_tokens:
        if token.revoked_at is None:
            token.revoked_at = datetime.now(timezone.utc)
    write_audit(db.session, request, principal, "user.reset_password", "user", user.id)
    commit()
    return ok({"status": "ok"})


@users_bp.post("/users/<uuid:user_id>/anonymize")
def anonymize_user(user_id):
    """Обезличивает учетную запись (152-ФЗ): ФИО, логин и почта заменяются,
    вход закрывается. Результаты занятий остаются для статистики."""
    principal = require("user.manage")
    user = get_or_404(User, user_id, "Пользователь")
    if user.id == principal.id:
        raise ApiError("Нельзя обезличить собственную учетную запись", 409)
    if user.anonymized_at is not None:
        raise ApiError("Учетная запись уже обезличена", 409)
    require_recent_backup()

    tag = user.id.hex[:8]
    user.full_name = f"Обезличенный пользователь {tag}"
    user.username = f"anon-{tag}"
    user.email = None
    user.mfa_enabled = False
    user.mfa_secret = None
    user.password_hash = hash_password(uuid.uuid4().hex + uuid.uuid4().hex)
    user.is_active = False
    user.is_blocked = True
    user.anonymized_at = datetime.now(timezone.utc)
    for token in user.refresh_tokens:
        if token.revoked_at is None:
            token.revoked_at = user.anonymized_at
    write_audit(db.session, request, principal, "user.anonymize", "user", user.id)
    commit()
    return ok(_user_view(user))


@users_bp.get("/roles")
def list_roles():
    current_user()
    return items(list(db.session.execute(select(Role).order_by(Role.id)).scalars()))


def _role_or_404(code):
    role = _role_by_code(code)
    if role is None:
        raise ApiError("Роль не найдена", 404)
    return role


def _set_role_permissions(role, codes):
    have = {p.code: p for p in db.session.execute(select(Permission)).scalars()}
    role.permissions = [have[c] for c in sorted(set(codes)) if c in have]


@users_bp.get("/roles/matrix")
def roles_matrix():
    require("user.manage")
    roles = list(db.session.execute(select(Role).order_by(Role.id)).scalars())
    return ok(
        {
            "permissions": [
                {"code": code, "description": text}
                for code, text in sorted(PERMISSIONS.items())
            ],
            "roles": [
                {
                    "code": role.code,
                    "name": role.name,
                    "permissions": sorted(p.code for p in role.permissions),
                    "default": sorted(ROLE_PERMISSIONS.get(role.code, [])),
                    "must_have": sorted(ROLE_MUST_HAVE.get(role.code, set())),
                    "forbidden": sorted(ROLE_FORBIDDEN.get(role.code, set())),
                }
                for role in roles
            ],
        }
    )


@users_bp.put("/roles/<code>/permissions")
def set_role_permissions(code):
    principal = require("user.manage")
    role = _role_or_404(code)
    payload = body(RolePermissionsIn)
    problems = check_role_permissions(role.code, payload.permissions)
    if problems:
        raise ApiError(
            "Набор прав нарушает ограничения",
            422,
            code="role_rules_violated",
            details={"problems": problems},
        )
    before = sorted(p.code for p in role.permissions)
    _set_role_permissions(role, payload.permissions)
    write_audit(
        db.session,
        request,
        principal,
        "role.permissions.update",
        "role",
        role.code,
        {
            "before": before,
            "after": sorted(set(payload.permissions)),
            "comment": payload.comment,
        },
    )
    commit()
    return ok(
        {
            **role.to_dict(),
            "applies": "сразу: права проверяются по БД при каждом запросе",
        }
    )


@users_bp.post("/roles/<code>/permissions/reset")
def reset_role_permissions(code):
    principal = require("user.manage")
    role = _role_or_404(code)
    before = sorted(p.code for p in role.permissions)
    _set_role_permissions(role, ROLE_PERMISSIONS[role.code])
    write_audit(
        db.session,
        request,
        principal,
        "role.permissions.reset",
        "role",
        role.code,
        {"before": before},
    )
    commit()
    return item(role)


@users_bp.get("/permissions")
def list_permissions():
    require("user.manage")
    return items(
        list(db.session.execute(select(Permission).order_by(Permission.code)).scalars())
    )


def _editable_group(group, principal):
    if is_admin(principal):
        return group
    if group.teacher_id != principal.id:
        raise ApiError("Группа другого преподавателя", 403)
    return group


@users_bp.get("/groups")
def list_groups():
    principal = require("user.manage", "session.manage", "session.participate")
    stmt = select(Group).order_by(Group.name)
    if principal.role.code == "teacher":
        stmt = stmt.where(Group.teacher_id == principal.id)
    elif principal.role.code == "student":
        stmt = stmt.where(Group.id.in_([g.id for g in principal.groups] or [None]))
    return ok(paginate(stmt))


@users_bp.post("/groups")
def create_group():
    principal = require("user.manage", "session.manage")
    payload = body(GroupIn)
    # преподаватель создает группы только на себя
    teacher_id = payload.teacher_id if is_admin(principal) else principal.id
    group = Group(name=payload.name, teacher_id=teacher_id)
    db.session.add(group)
    db.session.flush()
    if payload.member_ids:
        group.members = list(
            db.session.execute(
                select(User).where(User.id.in_(payload.member_ids))
            ).scalars()
        )
    write_audit(
        db.session,
        request,
        principal,
        "group.create",
        "group",
        group.id,
        {"members": len(group.members)},
    )
    commit()
    return item(group, 201)


@users_bp.get("/groups/<uuid:group_id>")
def get_group(group_id):
    principal = current_user()
    group = get_or_404(Group, group_id, "Группа")
    if principal.role.code == "student":
        if principal.id not in {m.id for m in group.members}:
            raise ApiError("Вы не состоите в этой группе", 403)
    elif not is_admin(principal) and group.teacher_id != principal.id:
        raise ApiError("Группа другого преподавателя", 403)
    return ok(
        {
            **group.to_dict(),
            "members_detail": [
                {"id": str(m.id), "full_name": m.full_name, "username": m.username}
                for m in group.members
            ],
        }
    )


@users_bp.patch("/groups/<uuid:group_id>")
def update_group(group_id):
    principal = require("user.manage", "session.manage")
    group = _editable_group(get_or_404(Group, group_id, "Группа"), principal)
    payload = body(GroupIn)
    group.name = payload.name
    if payload.teacher_id is not None and is_admin(principal):
        group.teacher_id = payload.teacher_id
    write_audit(db.session, request, principal, "group.update", "group", group.id)
    commit()
    return item(group)


@users_bp.post("/groups/<uuid:group_id>/members")
def add_members(group_id):
    principal = require("user.manage", "session.manage")
    group = _editable_group(get_or_404(Group, group_id, "Группа"), principal)
    payload = body(MembersIn)
    users = list(
        db.session.execute(select(User).where(User.id.in_(payload.user_ids))).scalars()
    )
    for user in users:
        if user not in group.members:
            group.members.append(user)
    write_audit(
        db.session,
        request,
        principal,
        "group.add_members",
        "group",
        group.id,
        {"count": len(users)},
    )
    commit()
    return item(group)


@users_bp.delete("/groups/<uuid:group_id>/members/<uuid:user_id>")
def remove_member(group_id, user_id):
    principal = require("user.manage", "session.manage")
    group = _editable_group(get_or_404(Group, group_id, "Группа"), principal)
    user = get_or_404(User, user_id, "Пользователь")
    if user in group.members:
        group.members.remove(user)
    write_audit(
        db.session,
        request,
        principal,
        "group.remove_member",
        "group",
        group.id,
        {"user_id": str(user_id)},
    )
    commit()
    return item(group)


@users_bp.delete("/groups/<uuid:group_id>")
def delete_group(group_id):
    principal = require("user.manage", "session.manage")
    group = _editable_group(get_or_404(Group, group_id, "Группа"), principal)
    if group.sessions:
        raise ApiError("Нельзя удалить группу, по которой проводились занятия", 409)
    require_recent_backup()
    db.session.delete(group)
    write_audit(db.session, request, principal, "group.delete", "group", group_id)
    commit()
    return ok({"status": "deleted"})
