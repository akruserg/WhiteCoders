from ..core.extensions import db
from .mixins import utcnow


class RefreshToken(db.Model):
    __tablename__ = "refresh_tokens"

    id = db.Column(
        db.UUID(as_uuid=True),
        primary_key=True,
        server_default=db.text("gen_random_uuid()"),
    )
    user_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash = db.Column(db.String(128), nullable=False, unique=True)
    issued_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    revoked_at = db.Column(db.DateTime(timezone=True))
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
