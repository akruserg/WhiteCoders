from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import JSONB

__all__ = ["utcnow", "JSONB"]


def utcnow():
    return datetime.now(timezone.utc)
