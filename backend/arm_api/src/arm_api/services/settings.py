from sqlalchemy import select

from ..core.extensions import db
from ..models import SystemSetting


def get(key, default=None):
    """Значение настройки из БД, а если ее нет - default (обычно из окружения).

    Настройки хранятся в БД, чтобы изменение администратора видели сразу все
    воркеры API, без перезапуска.
    """
    value = db.session.execute(
        select(SystemSetting.value).where(SystemSetting.key == key)
    ).scalar()
    return default if value is None else value


# Настройки производительности, которые применяются при запуске узла: ключ -> переменная
# окружения entrypoint.sh. Берутся только те, что администратор менял через API
# (updated_by заполнен); остальные остаются как в окружении.
PERF_ENV = {
    "perf.gunicorn_workers": "GUNICORN_WORKERS",
    "perf.gunicorn_threads": "GUNICORN_THREADS",
    "perf.db_pool_size": "DB_POOL_SIZE",
    "perf.request_timeout_sec": "GUNICORN_TIMEOUT",
}


def perf_env():
    """Переменные окружения из настроек производительности, измененных администратором."""
    rows = db.session.execute(
        select(SystemSetting.key, SystemSetting.value).where(
            SystemSetting.key.in_(list(PERF_ENV)), SystemSetting.updated_by.is_not(None)
        )
    ).all()
    result = {}
    for key, value in rows:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            result[PERF_ENV[key]] = number
    return result


def main():  # python -m arm_api.services.settings perf-env
    import sys

    if sys.argv[1:] != ["perf-env"]:
        raise SystemExit("usage: python -m arm_api.services.settings perf-env")
    from .. import create_app

    with create_app().app_context():
        try:
            values = perf_env()
        except Exception:  # БД еще недоступна: запускаемся с окружением
            values = {}
    for name, number in sorted(values.items()):
        print(f"export {name}={number}")  # только целые числа: безопасно для eval


if __name__ == "__main__":
    main()
