import uuid

import enum

from ..core.extensions import db
from .mixins import JSONB, UTCDateTime, utcnow

session_categories = db.Table(
    "session_categories",
    db.Column(
        "session_id",
        db.UUID(as_uuid=True),
        db.ForeignKey("training_sessions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    db.Column(
        "category_id",
        db.Integer,
        db.ForeignKey("incident_categories.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    db.Index("ix_session_categories_category_id", "category_id"),
)


class SessionStatus(enum.Enum):
    PLANNED = "planned"
    RUNNING = "running"
    FINISHED = "finished"
    CANCELLED = "cancelled"


class SessionMode(enum.Enum):
    CARDS = "cards"
    CARD_ACTIONS = "card_actions"
    MIXED = "mixed"


class QuestionSource(enum.Enum):
    GENERATED = "generated"
    STUDENT = "student"
    MIXED = "mixed"


class TrainingSession(db.Model):
    __tablename__ = "training_sessions"

    id = db.Column(
        db.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    title = db.Column(db.String(255), nullable=False)
    teacher_id = db.Column(
        db.UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False
    )
    group_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("groups.id", ondelete="SET NULL"),
    )
    mode = db.Column(
        db.Enum(SessionMode, name="session_mode", native_enum=True),
        nullable=False,
        default=SessionMode.CARDS,
    )
    question_source = db.Column(
        db.Enum(QuestionSource, name="question_source", native_enum=True),
        nullable=False,
        default=QuestionSource.GENERATED,
    )
    status = db.Column(
        db.Enum(SessionStatus, name="session_status", native_enum=True),
        nullable=False,
        default=SessionStatus.PLANNED,
    )
    grading_profile_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("grading_profiles.id", ondelete="SET NULL"),
    )
    difficulty_min = db.Column(db.SmallInteger, nullable=False, default=1)
    difficulty_max = db.Column(db.SmallInteger, nullable=False, default=5)
    time_limit_sec = db.Column(db.Integer, nullable=False, default=30)
    settings = db.Column(JSONB, nullable=False, default=dict)
    started_at = db.Column(UTCDateTime())
    finished_at = db.Column(UTCDateTime())
    created_at = db.Column(UTCDateTime(), nullable=False, default=utcnow)

    teacher = db.relationship("User", back_populates="training_sessions")
    group = db.relationship("Group", back_populates="sessions")
    grading_profile = db.relationship("GradingProfile", back_populates="sessions")
    categories = db.relationship(
        "IncidentCategory", secondary=session_categories, lazy="selectin"
    )
    participants = db.relationship(
        "SessionParticipant", back_populates="session", cascade="all, delete-orphan"
    )
    attempts = db.relationship(
        "Attempt", back_populates="session", cascade="all, delete-orphan"
    )
    reports = db.relationship("Report", back_populates="session")
    insights = db.relationship(
        "Insight",
        back_populates="session",
        foreign_keys="Insight.session_id",
    )

    __table_args__ = (
        db.Index("ix_training_sessions_teacher_id", "teacher_id"),
        db.Index("ix_training_sessions_group_id", "group_id"),
        db.Index("ix_training_sessions_status", "status"),
        db.CheckConstraint(
            "difficulty_min <= difficulty_max",
            name="ck_training_sessions_difficulty_range",
        ),
    )

    def to_dict(self):
        return {
            "id": str(self.id),
            "title": self.title,
            "teacher_id": str(self.teacher_id),
            "group_id": str(self.group_id) if self.group_id else None,
            "mode": self.mode.value,
            "question_source": self.question_source.value,
            "status": self.status.value,
            "grading_profile_id": (
                str(self.grading_profile_id) if self.grading_profile_id else None
            ),
            "category_ids": [category.id for category in self.categories],
            "difficulty_min": self.difficulty_min,
            "difficulty_max": self.difficulty_max,
            "time_limit_sec": self.time_limit_sec,
            "settings": self.settings,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "created_at": self.created_at.isoformat(),
        }
