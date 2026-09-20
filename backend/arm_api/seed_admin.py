"""
seed-скрипт: справочники, настройки и первый администратор

    docker compose exec arm_api python seed_admin.py --username admin --full-name "Администратор"

Пароль берется из ADMIN_PASSWORD или из --password. Значения по умолчанию нет:
пароль администратора не должен быть известен заранее. Справочники
(классификатор, шаблон карточки, права) при обычном запуске контейнера
создаются автоматически, скрипт нужен, чтобы завести администратора.
"""

import argparse
import os
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default=os.environ.get("ADMIN_PASSWORD"))
    parser.add_argument("--full-name", default="Администратор")
    parser.add_argument("--email", default=None)
    parser.add_argument("--demo", action="store_true", help="добавить демо-сценарии")
    args = parser.parse_args()
    if not args.password:
        parser.error("укажите --password или задайте ADMIN_PASSWORD")

    from arm_api import create_app
    from arm_api.core.security import check_password_policy
    from arm_api.services import seed

    app = create_app()
    with app.app_context():
        print("[seed]", seed.seed_all(demo=args.demo))
        check_password_policy(args.password)
        if seed.ensure_admin(args.username, args.password, args.full_name, args.email):
            print(f"[seed] создан администратор: {args.username}")
        else:
            print(f"[seed] пользователь {args.username!r} уже существует, пропуск")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[seed] ОШИБКА: {exc}", file=sys.stderr)
        sys.exit(1)
