import uuid

from ..core.extensions import db
from .mixins import JSONB, UTCDateTime, utcnow


class SystemUpdate(db.Model):
    """Примененный пакет обновления (учебный контент и настройки)."""

    __tablename__ = "system_updates"

    id = db.Column(db.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version = db.Column(db.String(64), nullable=False)
    title = db.Column(db.String(255))
    checksum = db.Column(db.String(64), nullable=False, unique=True)  # sha256 пакета
    summary = db.Column(JSONB, nullable=False, default=dict)
    applied_by = db.Column(
        db.UUID(as_uuid=True), db.ForeignKey("users.id", ondelete="SET NULL")
    )
    applied_at = db.Column(UTCDateTime(), nullable=False, default=utcnow)

    def to_dict(self):
        return {
            "id": str(self.id),
            "version": self.version,
            "title": self.title,
            "checksum": self.checksum,
            "summary": self.summary,
            "applied_by": str(self.applied_by) if self.applied_by else None,
            "applied_at": self.applied_at.isoformat(),
        }
