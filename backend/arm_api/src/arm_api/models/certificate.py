import uuid

from ..core.extensions import db
from .mixins import JSONB, UTCDateTime, utcnow


class Certificate(db.Model):
    __tablename__ = "certificates"

    id = db.Column(
        db.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    number = db.Column(db.String(64), nullable=False, unique=True)
    user_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("training_sessions.id", ondelete="SET NULL"),
    )
    issued_by = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("users.id", ondelete="SET NULL"),
    )
    score = db.Column(db.Numeric(5, 2), nullable=False)
    issued_at = db.Column(UTCDateTime(), nullable=False, default=utcnow)
    valid_until = db.Column(UTCDateTime())
    file_path = db.Column(db.String(512))
    payload = db.Column(JSONB, nullable=False, default=dict)

    user = db.relationship(
        "User", back_populates="certificates", foreign_keys=[user_id]
    )
    session = db.relationship("TrainingSession")
    issuer = db.relationship("User", foreign_keys=[issued_by])

    __table_args__ = (
        db.Index("ix_certificates_user_id", "user_id"),
        db.Index("ix_certificates_session_id", "session_id"),
    )

    def to_dict(self):
        return {
            "id": str(self.id),
            "number": self.number,
            "user_id": str(self.user_id),
            "session_id": str(self.session_id) if self.session_id else None,
            "issued_by": str(self.issued_by) if self.issued_by else None,
            "score": float(self.score),
            "issued_at": self.issued_at.isoformat(),
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
            "file_path": self.file_path,
            "payload": self.payload,
        }
