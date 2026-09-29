"""Работа нескольких узлов API с одной БД (локальный кластер).

Узлы равноправны и не хранят состояния между запросами, поэтому любой узел может
обслужить любой запрос. Единственное, что должно выполняться ровно на одном узле,
- миграции БД и фоновые задания (бэкап, очистка журнала). Для этого используются
блокировки самой СУБД: PostgreSQL - advisory lock, MySQL и MariaDB - GET_LOCK.
Если узел с заданием упал, блокировка снимается вместе с его соединением, и
следующий такт подхватывает другой узел.

    python -m arm_api.services.cluster init [--demo]   # миграции + начальные данные, один раз на кластер
"""

import argparse
import hashlib
import logging
import os
import socket
from contextlib import contextmanager

from sqlalchemy import text

from ..core.extensions import db

logger = logging.getLogger(__name__)

NODE_ID = os.environ.get("NODE_ID") or socket.gethostname()


def _key(name):
    # 63-битное число из имени: одно и то же на всех узлах
    return (
        int.from_bytes(hashlib.sha256(f"arm112:{name}".encode()).digest()[:8], "big")
        >> 1
    )


@contextmanager
def lock(name, wait=False, timeout_sec=300):
    """Блокировка на весь кластер. Отдает True, если блокировка получена.

    wait=False: не ждать, если ее держит другой узел (для периодических заданий).
    wait=True: ждать до timeout_sec (для миграций при одновременном старте узлов).
    """
    dialect = db.engine.dialect.name
    if dialect not in {"postgresql", "mysql", "mariadb"}:
        yield True  # SQLite - один узел, конкурировать не с кем
        return

    connection = db.engine.connect()  # своя связь: блокировка живет, пока она открыта
    got = False
    try:
        got = _acquire(connection, dialect, name, wait, timeout_sec)
        yield got
    finally:
        if got:
            _release(connection, dialect, name)
        connection.close()


def _acquire(connection, dialect, name, wait, timeout_sec):
    if dialect == "postgresql":
        if wait:
            connection.execute(
                text("SET lock_timeout = :ms"), {"ms": timeout_sec * 1000}
            )
            connection.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _key(name)})
            return True
        return bool(
            connection.execute(
                text("SELECT pg_try_advisory_lock(:k)"), {"k": _key(name)}
            ).scalar()
        )
    row = connection.execute(
        text("SELECT GET_LOCK(:n, :t)"),
        {"n": f"arm112:{name}", "t": timeout_sec if wait else 0},
    ).scalar()
    return row == 1


def _release(connection, dialect, name):
    if dialect == "postgresql":
        connection.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _key(name)})
    else:
        connection.execute(text("SELECT RELEASE_LOCK(:n)"), {"n": f"arm112:{name}"})


def init(demo=False):
    """Миграции и начальные данные. Под блокировкой: при одновременном старте
    нескольких узлов выполняет один, остальные ждут и видят готовую схему."""
    from flask_migrate import upgrade

    from . import seed

    with lock("init", wait=True, timeout_sec=600):
        upgrade(
            directory=os.path.join(
                os.path.dirname(__file__), "..", "..", "..", "migrations"
            )
        )
        seed.seed_all(demo=demo)
        username, password = os.environ.get("ADMIN_USERNAME"), os.environ.get(
            "ADMIN_PASSWORD"
        )
        if username and password and seed.ensure_admin(username, password):
            logger.info("Создан администратор %s", username)


def main():
    parser = argparse.ArgumentParser(description="Кластер API")
    parser.add_argument("command", choices=["init"])
    parser.add_argument("--demo", action="store_true", help="демонстрационные сценарии")
    args = parser.parse_args()

    from arm_api import app

    with app.app_context():
        init(demo=args.demo)
    print("[cluster] схема и начальные данные готовы")


if __name__ == "__main__":
    main()
