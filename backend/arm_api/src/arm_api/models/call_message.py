from ..core.extensions import db
from .mixins import BigIntPK, UTCDateTime, utcnow


class CallMessage(db.Model):
    __tablename__ = "call_messages"

    id = db.Column(BigIntPK, primary_key=True)
    call_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("calls.id", ondelete="CASCADE"),
        nullable=False,
    )
    author = db.Column(db.String(16), nullable=False)
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(UTCDateTime(), nullable=False, default=utcnow)

    call = db.relationship("Call", back_populates="messages")

    __table_args__ = (
        db.Index("ix_call_messages_call_id_created", "call_id", "created_at"),
        db.CheckConstraint(
            "author IN ('caller', 'operator', 'system')",
            name="ck_call_messages_author",
        ),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "call_id": str(self.call_id),
            "author": self.author,
            "text": self.text,
            "created_at": self.created_at.isoformat(),
        }
