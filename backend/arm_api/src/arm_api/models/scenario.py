import uuid

import enum

from ..core.extensions import db
from .mixins import JSONB, UTCDateTime, pg_only, utcnow


class ScenarioOrigin(enum.Enum):
    MANUAL = "manual"
    AI = "ai"
    IMPORTED = "imported"
    STUDENT = "student"


class ScenarioStatus(enum.Enum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    PARTIALLY_VALIDATED = "partially_validated"
    VALIDATED = "validated"
    ARCHIVED = "archived"


class Scenario(db.Model):
    __tablename__ = "scenarios"

    id = db.Column(
        db.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    title = db.Column(db.String(255), nullable=False)
    category_id = db.Column(
        db.Integer, db.ForeignKey("incident_categories.id"), nullable=False
    )
    template_id = db.Column(
        db.UUID(as_uuid=True), db.ForeignKey("card_templates.id"), nullable=False
    )
    difficulty = db.Column(db.SmallInteger, nullable=False, default=1)
    origin = db.Column(
        db.Enum(ScenarioOrigin, name="scenario_origin", native_enum=True),
        nullable=False,
        default=ScenarioOrigin.MANUAL,
    )
    status = db.Column(
        db.Enum(ScenarioStatus, name="scenario_status", native_enum=True),
        nullable=False,
        default=ScenarioStatus.DRAFT,
    )
    legend = db.Column(JSONB, nullable=False)
    reference_card = db.Column(JSONB, nullable=False)
    reference_actions = db.Column(JSONB, nullable=False, default=list)
    time_limit_sec = db.Column(db.Integer, nullable=False, default=30)
    grading_profile_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("grading_profiles.id", ondelete="SET NULL"),
    )

    source_attempt_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey(
            "attempts.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_scenarios_source_attempt",
        ),
    )

    author_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("users.id", ondelete="SET NULL"),
    )
    validated_by = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("users.id", ondelete="SET NULL"),
    )
    validated_at = db.Column(UTCDateTime())

    validated_fields = db.Column(JSONB, nullable=False, default=dict)

    ai_model = db.Column(db.String(64))
    created_at = db.Column(UTCDateTime(), nullable=False, default=utcnow)
    updated_at = db.Column(
        UTCDateTime(), nullable=False, default=utcnow, onupdate=utcnow
    )

    category = db.relationship("IncidentCategory", back_populates="scenarios")
    template = db.relationship("CardTemplate", back_populates="scenarios")
    grading_profile = db.relationship("GradingProfile", back_populates="scenarios")
    author = db.relationship(
        "User", back_populates="authored_scenarios", foreign_keys=[author_id]
    )
    validator = db.relationship(
        "User", back_populates="validated_scenarios", foreign_keys=[validated_by]
    )
    source_attempt = db.relationship(
        "Attempt",
        foreign_keys=[source_attempt_id],
        back_populates="derived_scenarios",
        post_update=True,
    )
    corrections = db.relationship(
        "ScenarioCorrection", back_populates="scenario", cascade="all, delete-orphan"
    )
    attempts = db.relationship(
        "Attempt", back_populates="scenario", foreign_keys="Attempt.scenario_id"
    )

    __table_args__ = (
        db.Index("ix_scenarios_category_id", "category_id"),
        db.Index("ix_scenarios_status_origin", "status", "origin"),
        db.Index("ix_scenarios_difficulty", "difficulty"),
        *pg_only(
            db.Index(
                "ix_scenarios_reference_card", "reference_card", postgresql_using="gin"
            )
        ),
        db.CheckConstraint(
            "difficulty BETWEEN 1 AND 5", name="ck_scenarios_difficulty"
        ),
        db.CheckConstraint("time_limit_sec > 0", name="ck_scenarios_time_limit"),
    )

    def to_dict(self):
        return {
            "id": str(self.id),
            "title": self.title,
            "category_id": self.category_id,
            "template_id": str(self.template_id),
            "difficulty": self.difficulty,
            "origin": self.origin.value,
            "status": self.status.value,
            "legend": self.legend,
            "reference_card": self.reference_card,
            "reference_actions": self.reference_actions,
            "time_limit_sec": self.time_limit_sec,
            "grading_profile_id": (
                str(self.grading_profile_id) if self.grading_profile_id else None
            ),
            "source_attempt_id": (
                str(self.source_attempt_id) if self.source_attempt_id else None
            ),
            "author_id": str(self.author_id) if self.author_id else None,
            "validated_by": str(self.validated_by) if self.validated_by else None,
            "validated_at": (
                self.validated_at.isoformat() if self.validated_at else None
            ),
            "validated_fields": self.validated_fields,
            "ai_model": self.ai_model,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
