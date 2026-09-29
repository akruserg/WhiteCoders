import os
import uuid  # noqa: F401  (используется моделями: default=uuid.uuid4)
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Integer, JSON
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import TypeDecorator

__all__ = ["utcnow", "JSONB", "BigIntPK", "UTCDateTime", "IS_PG", "pg_only"]

# Основная СУБД - PostgreSQL. Модели переносимы и на MySQL/MariaDB и SQLite:
# типы, зависящие от диалекта, подменяются здесь, а не в каждой модели.
IS_PG = os.environ.get("DATABASE_URL", "postgresql").startswith("postgresql")

# JSON: на PostgreSQL бинарный JSONB, на остальных обычный JSON
JSONB = JSON().with_variant(postgresql.JSONB(), "postgresql")

# Числовой первичный ключ: SQLite автоинкрементит только INTEGER PRIMARY KEY
BigIntPK = BigInteger().with_variant(Integer, "sqlite")


def utcnow():
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Момент времени в UTC на любой СУБД.

    PostgreSQL хранит timestamptz, MySQL и SQLite - дату без пояса. Тип всегда
    записывает время в UTC и всегда возвращает aware-datetime в UTC, поэтому код
    не зависит от того, вернул ли драйвер часовой пояс.
    """

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(DateTime(timezone=True))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value = value.astimezone(timezone.utc)
        return value if dialect.name == "postgresql" else value.replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def pg_only(index):
    """Индексы GIN и частичные уникальные есть только в PostgreSQL. В остальных
    СУБД их роль (например, «одна активная версия шаблона») выполняет код."""
    return (index,) if IS_PG else ()
