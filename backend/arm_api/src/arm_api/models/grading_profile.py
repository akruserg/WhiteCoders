import uuid

from ..core.extensions import db
from .mixins import JSONB, UTCDateTime, pg_only, utcnow


class GradingProfile(db.Model):
    __tablename__ = "grading_profiles"

    id = db.Column(
        db.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name = db.Column(db.String(128), nullable=False)
    owner_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("users.id", ondelete="SET NULL"),
    )
    category_id = db.Column(
        db.Integer,
        db.ForeignKey("incident_categories.id", ondelete="SET NULL"),
    )

    max_content_errors = db.Column(db.SmallInteger, nullable=False, default=0)
    max_grammar_errors = db.Column(db.SmallInteger, nullable=False, default=2)
    max_procedure_errors = db.Column(db.SmallInteger, nullable=False, default=0)
    max_missing_fields = db.Column(db.SmallInteger, nullable=False, default=0)

    default_time_limit_sec = db.Column(db.Integer, nullable=False, default=30)
    time_overrun_tolerance_pct = db.Column(db.SmallInteger, nullable=False, default=10)
    pass_score = db.Column(db.Numeric(5, 2), nullable=False, default=70)

    grammar_check_enabled = db.Column(db.Boolean, nullable=False, default=True)
    syntax_rules = db.Column(JSONB, nullable=False, default=dict)

    error_weights = db.Column(JSONB, nullable=False, default=dict)

    is_default = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(UTCDateTime(), nullable=False, default=utcnow)
    updated_at = db.Column(
        UTCDateTime(), nullable=False, default=utcnow, onupdate=utcnow
    )

    owner = db.relationship("User", back_populates="grading_profiles")
    category = db.relationship("IncidentCategory", back_populates="grading_profiles")
    sessions = db.relationship("TrainingSession", back_populates="grading_profile")
    scenarios = db.relationship("Scenario", back_populates="grading_profile")

    __table_args__ = (
        db.Index("ix_grading_profiles_owner_id", "owner_id"),
        *pg_only(
            db.Index(
                "uq_grading_profiles_single_default",
                "is_default",
                unique=True,
                postgresql_where=db.text("is_default"),
            )
        ),
        db.CheckConstraint(
            "pass_score >= 0 AND pass_score <= 100",
            name="ck_grading_profiles_pass_score",
        ),
    )

    def to_dict(self):
        return {
            "id": str(self.id),
            "name": self.name,
            "owner_id": str(self.owner_id) if self.owner_id else None,
            "category_id": self.category_id,
            "max_content_errors": self.max_content_errors,
            "max_grammar_errors": self.max_grammar_errors,
            "max_procedure_errors": self.max_procedure_errors,
            "max_missing_fields": self.max_missing_fields,
            "default_time_limit_sec": self.default_time_limit_sec,
            "time_overrun_tolerance_pct": self.time_overrun_tolerance_pct,
            "pass_score": float(self.pass_score),
            "grammar_check_enabled": self.grammar_check_enabled,
            "syntax_rules": self.syntax_rules,
            "error_weights": self.error_weights,
            "is_default": self.is_default,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
