import uuid

from ..core.extensions import db
from .mixins import UTCDateTime, utcnow


class Backup(db.Model):
    __tablename__ = "backups"

    id = db.Column(
        db.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    started_at = db.Column(UTCDateTime(), nullable=False, default=utcnow)
    finished_at = db.Column(UTCDateTime())
    status = db.Column(db.String(16), nullable=False, default="running")
    kind = db.Column(db.String(16), nullable=False, default="full")
    is_automatic = db.Column(db.Boolean, nullable=False, default=True)
    file_path = db.Column(db.String(512))
    size_bytes = db.Column(db.BigInteger)
    checksum = db.Column(db.String(128))
    error = db.Column(db.Text)
    created_by = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("users.id", ondelete="SET NULL"),
    )

    creator = db.relationship("User")

    __table_args__ = (
        db.Index("ix_backups_started_at", "started_at"),
        db.CheckConstraint(
            "status IN ('running', 'success', 'failed')", name="ck_backups_status"
        ),
    )

    def to_dict(self):
        return {
            "id": str(self.id),
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "status": self.status,
            "kind": self.kind,
            "is_automatic": self.is_automatic,
            "file_path": self.file_path,
            "size_bytes": self.size_bytes,
            "checksum": self.checksum,
            "error": self.error,
            "created_by": str(self.created_by) if self.created_by else None,
        }
