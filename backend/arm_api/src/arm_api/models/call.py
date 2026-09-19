import enum

from ..core.extensions import db
from .mixins import utcnow


class CallChannel(enum.Enum):
    VOIP = "voip"
    TEXT = "text"


class CallStatus(enum.Enum):
    RINGING = "ringing"
    ANSWERED = "answered"
    MISSED = "missed"
    FINISHED = "finished"


class Call(db.Model):
    __tablename__ = "calls"

    id = db.Column(
        db.UUID(as_uuid=True),
        primary_key=True,
        server_default=db.text("gen_random_uuid()"),
    )
    attempt_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("attempts.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel = db.Column(
        db.Enum(CallChannel, name="call_channel", native_enum=True),
        nullable=False,
        default=CallChannel.TEXT,
    )
    sip_call_id = db.Column(db.String(128))
    caller_number = db.Column(db.String(32))
    status = db.Column(
        db.Enum(CallStatus, name="call_status", native_enum=True),
        nullable=False,
        default=CallStatus.RINGING,
    )
    ring_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    answer_at = db.Column(db.DateTime(timezone=True))
    finish_at = db.Column(db.DateTime(timezone=True))
    answer_delay_ms = db.Column(db.Integer)
    rtt_ms = db.Column(db.Integer)
    audio_path = db.Column(db.String(512))
    audio_format = db.Column(db.String(8))
    transcript = db.Column(db.Text)

    attempt = db.relationship("Attempt", back_populates="calls")
    messages = db.relationship(
        "CallMessage", back_populates="call", cascade="all, delete-orphan"
    )

    __table_args__ = (
        db.Index("ix_calls_attempt_id", "attempt_id"),
        db.Index("ix_calls_sip_call_id", "sip_call_id"),
        db.Index("ix_calls_status", "status"),
    )

    def to_dict(self):
        return {
            "id": str(self.id),
            "attempt_id": str(self.attempt_id),
            "channel": self.channel.value,
            "sip_call_id": self.sip_call_id,
            "caller_number": self.caller_number,
            "status": self.status.value,
            "ring_at": self.ring_at.isoformat(),
            "answer_at": self.answer_at.isoformat() if self.answer_at else None,
            "finish_at": self.finish_at.isoformat() if self.finish_at else None,
            "answer_delay_ms": self.answer_delay_ms,
            "rtt_ms": self.rtt_ms,
            "audio_path": self.audio_path,
            "audio_format": self.audio_format,
            "transcript": self.transcript,
        }
