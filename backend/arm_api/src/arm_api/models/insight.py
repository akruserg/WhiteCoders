import uuid

import enum

from ..core.extensions import db
from .mixins import JSONB, UTCDateTime, utcnow


class InsightKind(enum.Enum):
    GROUP_TYPICAL_ERRORS = "group_typical_errors"
    STUDENT_RECOMMENDATION = "student_recommendation"
    SESSION_SUMMARY = "session_summary"


class Insight(db.Model):
    __tablename__ = "insights"

    id = db.Column(
        db.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    kind = db.Column(
        db.Enum(InsightKind, name="insight_kind", native_enum=True), nullable=False
    )
    session_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("training_sessions.id", ondelete="CASCADE"),
    )
    target_user_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("users.id", ondelete="CASCADE"),
    )
    target_group_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("groups.id", ondelete="CASCADE"),
    )
    title = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text, nullable=False)

    data = db.Column(JSONB, nullable=False, default=dict)
    confidence = db.Column(db.Numeric(4, 3))
    ai_model = db.Column(db.String(64))
    is_published = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(UTCDateTime(), nullable=False, default=utcnow)

    session = db.relationship(
        "TrainingSession", back_populates="insights", foreign_keys=[session_id]
    )
    target_user = db.relationship(
        "User", back_populates="insights", foreign_keys=[target_user_id]
    )
    target_group = db.relationship(
        "Group", back_populates="insights", foreign_keys=[target_group_id]
    )

    __table_args__ = (
        db.Index("ix_insights_target_user_id", "target_user_id"),
        db.Index("ix_insights_target_group_id", "target_group_id"),
        db.Index("ix_insights_session_kind", "session_id", "kind"),
        db.CheckConstraint(
            "target_user_id IS NOT NULL OR target_group_id IS NOT NULL "
            "OR session_id IS NOT NULL",
            name="ck_insights_has_target",
        ),
    )

    def to_dict(self):
        return {
            "id": str(self.id),
            "kind": self.kind.value,
            "session_id": str(self.session_id) if self.session_id else None,
            "target_user_id": (
                str(self.target_user_id) if self.target_user_id else None
            ),
            "target_group_id": (
                str(self.target_group_id) if self.target_group_id else None
            ),
            "title": self.title,
            "body": self.body,
            "data": self.data,
            "confidence": (
                float(self.confidence) if self.confidence is not None else None
            ),
            "ai_model": self.ai_model,
            "is_published": self.is_published,
            "created_at": self.created_at.isoformat(),
        }
