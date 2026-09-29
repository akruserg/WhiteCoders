from ..core.extensions import db
from .mixins import BigIntPK, JSONB, UTCDateTime, utcnow


class AuditLog(db.Model):
    __tablename__ = "audit_log"

    id = db.Column(BigIntPK, primary_key=True)
    ts = db.Column(UTCDateTime(), nullable=False, default=utcnow)
    user_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("users.id", ondelete="SET NULL"),
    )
    role_code = db.Column(db.String(32))
    action = db.Column(db.String(64), nullable=False)
    object_type = db.Column(db.String(64))
    object_id = db.Column(db.String(64))
    ip = db.Column(db.String(64))
    user_agent = db.Column(db.String(255))
    payload = db.Column(JSONB, nullable=False, default=dict)
    prev_hash = db.Column(db.String(64))
    entry_hash = db.Column(db.String(64))

    user = db.relationship("User", back_populates="audit_logs")

    __table_args__ = (
        db.Index("ix_audit_log_ts", "ts"),
        db.Index("ix_audit_log_user_ts", "user_id", "ts"),
        db.Index("ix_audit_log_object", "object_type", "object_id"),
        db.Index("ix_audit_log_action", "action"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "ts": self.ts.isoformat(),
            "user_id": str(self.user_id) if self.user_id else None,
            "role_code": self.role_code,
            "action": self.action,
            "object_type": self.object_type,
            "object_id": self.object_id,
            "ip": self.ip,
            "user_agent": self.user_agent,
            "payload": self.payload,
            "entry_hash": self.entry_hash,
        }
