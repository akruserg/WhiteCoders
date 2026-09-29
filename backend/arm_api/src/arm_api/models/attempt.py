import uuid

import enum

from ..core.extensions import db
from .mixins import JSONB, UTCDateTime, pg_only, utcnow


class AttemptStatus(enum.Enum):
    ISSUED = "issued"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    EXPIRED = "expired"
    EVALUATED = "evaluated"


class EvaluationSource(enum.Enum):
    AI = "ai"
    EXPERT = "expert"
    HYBRID = "hybrid"


class Attempt(db.Model):
    __tablename__ = "attempts"

    id = db.Column(
        db.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    session_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("training_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    scenario_id = db.Column(
        db.UUID(as_uuid=True), db.ForeignKey("scenarios.id"), nullable=False
    )
    seq = db.Column(db.Integer, nullable=False)
    status = db.Column(
        db.Enum(AttemptStatus, name="attempt_status", native_enum=True),
        nullable=False,
        default=AttemptStatus.ISSUED,
    )
    issued_at = db.Column(UTCDateTime(), nullable=False, default=utcnow)
    started_at = db.Column(UTCDateTime())
    submitted_at = db.Column(UTCDateTime())
    duration_ms = db.Column(db.Integer)

    time_limit_sec = db.Column(db.Integer, nullable=False, default=30)
    answer = db.Column(JSONB, nullable=False, default=dict)
    actions = db.Column(JSONB, nullable=False, default=list)

    score = db.Column(db.Numeric(5, 2))
    # прогноз балла на момент выдачи карточки; сравнивается с фактом (analytics.forecast_accuracy)
    forecast_score = db.Column(db.Numeric(5, 2))
    passed = db.Column(db.Boolean)
    evaluation = db.Column(JSONB)
    evaluated_by = db.Column(
        db.Enum(EvaluationSource, name="evaluation_source", native_enum=True)
    )
    evaluated_at = db.Column(UTCDateTime())
    ai_model = db.Column(db.String(64))

    expert_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("users.id", ondelete="SET NULL"),
    )
    expert_score = db.Column(db.Numeric(5, 2))
    expert_comment = db.Column(db.Text)
    expert_reviewed_at = db.Column(UTCDateTime())

    session = db.relationship("TrainingSession", back_populates="attempts")
    user = db.relationship("User", back_populates="attempts", foreign_keys=[user_id])
    expert = db.relationship(
        "User", back_populates="expert_reviews", foreign_keys=[expert_id]
    )
    scenario = db.relationship(
        "Scenario", back_populates="attempts", foreign_keys=[scenario_id]
    )
    derived_scenarios = db.relationship(
        "Scenario",
        back_populates="source_attempt",
        foreign_keys="Scenario.source_attempt_id",
    )
    errors = db.relationship(
        "AttemptError", back_populates="attempt", cascade="all, delete-orphan"
    )
    calls = db.relationship(
        "Call", back_populates="attempt", cascade="all, delete-orphan"
    )

    __table_args__ = (
        db.UniqueConstraint("session_id", "user_id", "seq"),
        db.Index("ix_attempts_session_id", "session_id"),
        db.Index("ix_attempts_user_id", "user_id"),
        db.Index("ix_attempts_scenario_id", "scenario_id"),
        db.Index("ix_attempts_status", "status"),
        db.Index("ix_attempts_submitted_at", "submitted_at"),
        *pg_only(db.Index("ix_attempts_answer", "answer", postgresql_using="gin")),
        db.CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 100)",
            name="ck_attempts_score_range",
        ),
    )

    @property
    def time_overrun_ms(self):

        if self.duration_ms is None:
            return None
        return self.duration_ms - self.time_limit_sec * 1000

    @property
    def final_score(self):

        value = self.expert_score if self.expert_score is not None else self.score
        return float(value) if value is not None else None

    def to_dict(self):
        return {
            "id": str(self.id),
            "session_id": str(self.session_id),
            "user_id": str(self.user_id),
            "scenario_id": str(self.scenario_id),
            "seq": self.seq,
            "status": self.status.value,
            "issued_at": self.issued_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "submitted_at": (
                self.submitted_at.isoformat() if self.submitted_at else None
            ),
            "duration_ms": self.duration_ms,
            "time_limit_sec": self.time_limit_sec,
            "time_overrun_ms": self.time_overrun_ms,
            "answer": self.answer,
            "actions": self.actions,
            "score": float(self.score) if self.score is not None else None,
            "passed": self.passed,
            "evaluation": self.evaluation,
            "evaluated_by": self.evaluated_by.value if self.evaluated_by else None,
            "evaluated_at": (
                self.evaluated_at.isoformat() if self.evaluated_at else None
            ),
            "ai_model": self.ai_model,
            "expert_id": str(self.expert_id) if self.expert_id else None,
            "expert_score": (
                float(self.expert_score) if self.expert_score is not None else None
            ),
            "expert_comment": self.expert_comment,
            "expert_reviewed_at": (
                self.expert_reviewed_at.isoformat() if self.expert_reviewed_at else None
            ),
            "final_score": self.final_score,
        }
