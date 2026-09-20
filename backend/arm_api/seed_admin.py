"""
seed-скрипт

наполняет справочники RBAC и создает первого администратора (если его нет)

docker compose exec arm_api python seed_admin.py --username admin --password "password123" --full-name "Администратор"
"""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="password123")
    parser.add_argument("--full-name", default="Администратор")
    parser.add_argument("--email", default=None)
    args = parser.parse_args()

    from arm_api import create_app
    from arm_api.core.extensions import db
    from arm_api.core.security import (
        PERMISSIONS,
        ROLE_PERMISSIONS,
        check_password_policy,
        hash_password,
    )
    from arm_api.models import Permission, Role, User
    from sqlalchemy import select

    app = create_app()

    with app.app_context():
        # 1. permissions
        existing_perm_codes = set(
            db.session.execute(select(Permission.code)).scalars()
        )
        for code, description in PERMISSIONS.items():
            if code not in existing_perm_codes:
                db.session.add(Permission(code=code, description=description))
        db.session.flush()

        # 2. roles
        role_codes = {"admin": 1, "teacher": 2, "student": 3}
        role_names = {
            "admin": "Администратор",
            "teacher": "Преподаватель",
            "student": "Обучающийся",
        }
        roles_by_code = {}
        for code, role_id in role_codes.items():
            role = db.session.execute(
                select(Role).where(Role.code == code)
            ).scalars().first()
            if role is None:
                role = Role(id=role_id, code=code, name=role_names[code])
                db.session.add(role)
                db.session.flush()
            roles_by_code[code] = role

        # 3. role_permissions
        all_permissions = {
            p.code: p for p in db.session.execute(select(Permission)).scalars()
        }
        for code, perm_codes in ROLE_PERMISSIONS.items():
            role = roles_by_code[code]
            current = {p.code for p in role.permissions}
            for perm_code in perm_codes:
                if perm_code not in current:
                    role.permissions.append(all_permissions[perm_code])
        db.session.commit()
        print("[seed] permissions/roles/role_permissions готовы")

        # 4. первый admin-пользователь
        existing_user = db.session.execute(
            select(User).where(User.username == args.username)
        ).scalars().first()
        if existing_user is not None:
            print(f"[seed] пользователь {args.username!r} уже существует, пропуск")
            return

        check_password_policy(args.password)
        admin_role = roles_by_code["admin"]
        user = User(
            username=args.username,
            full_name=args.full_name,
            email=args.email,
            password_hash=hash_password(args.password),
            role_id=admin_role.id,
            is_active=True,
        )
        db.session.add(user)
        db.session.commit()
        print(f"[seed] создан администратор: {args.username} / {args.password}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[seed] ОШИБКА: {exc}", file=sys.stderr)
        sys.exit(1)
