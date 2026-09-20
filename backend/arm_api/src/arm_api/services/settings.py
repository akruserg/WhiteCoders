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
