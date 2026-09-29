import uuid

from ..core.extensions import db
from .mixins import UTCDateTime, utcnow


class RefreshToken(db.Model):
    __tablename__ = "refresh_tokens"

    id = db.Column(
        db.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash = db.Column(db.String(128), nullable=False, unique=True)
    issued_at = db.Column(UTCDateTime(), nullable=False, default=utcnow)
    expires_at = db.Column(UTCDateTime(), nullable=False)
    revoked_at = db.Column(UTCDateTime())
    user_agent = db.Column(db.String(255))
    ip = db.Column(db.String(64))

    user = db.relationship("User", back_populates="refresh_tokens")

    __table_args__ = (
        db.Index("ix_refresh_tokens_user_id", "user_id"),
        db.Index("ix_refresh_tokens_expires_at", "expires_at"),
    )

    def to_dict(self):
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "user_agent": self.user_agent,
            "ip": self.ip,
        }
