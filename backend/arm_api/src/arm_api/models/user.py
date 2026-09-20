from ..core.extensions import db
from .mixins import utcnow


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(
        db.UUID(as_uuid=True),
        primary_key=True,
        server_default=db.text("gen_random_uuid()"),
    )
    username = db.Column(db.String(64), nullable=False, unique=True)
    full_name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255))
    password_hash = db.Column(db.String(255), nullable=False)
    role_id = db.Column(db.SmallInteger, db.ForeignKey("roles.id"), nullable=False)
    mfa_enabled = db.Column(db.Boolean, nullable=False, default=False)
    mfa_secret = db.Column(db.String(64))
    pd_consent_at = db.Column(db.DateTime(timezone=True))
    anonymized_at = db.Column(db.DateTime(timezone=True))
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    is_blocked = db.Column(db.Boolean, nullable=False, default=False)
    failed_attempts = db.Column(db.SmallInteger, nullable=False, default=0)
    last_login_at = db.Column(db.DateTime(timezone=True))
    password_changed_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    role = db.relationship("Role", back_populates="users")
    refresh_tokens = db.relationship(
        "RefreshToken", back_populates="user", cascade="all, delete-orphan"
    )
    groups = db.relationship(
        "Group",
        secondary="group_members",
        back_populates="members",
        lazy="selectin",
    )
    taught_groups = db.relationship(
        "Group", back_populates="teacher", foreign_keys="Group.teacher_id"
    )
    service_scope = db.relationship(
        "IncidentCategory",
        secondary="user_service_scope",
        back_populates="scoped_users",
        lazy="selectin",
    )
    authored_scenarios = db.relationship(
        "Scenario", back_populates="author", foreign_keys="Scenario.author_id"
    )
    validated_scenarios = db.relationship(
        "Scenario", back_populates="validator", foreign_keys="Scenario.validated_by"
    )
    scenario_corrections = db.relationship(
        "ScenarioCorrection", back_populates="author"
    )
    uploaded_materials = db.relationship("Material", back_populates="uploader")
    training_sessions = db.relationship("TrainingSession", back_populates="teacher")
    session_participations = db.relationship(
        "SessionParticipant", back_populates="user", cascade="all, delete-orphan"
    )
    attempts = db.relationship(
        "Attempt", back_populates="user", foreign_keys="Attempt.user_id"
    )
    expert_reviews = db.relationship(
        "Attempt", back_populates="expert", foreign_keys="Attempt.expert_id"
    )
    grading_profiles = db.relationship("GradingProfile", back_populates="owner")
    reports = db.relationship("Report", back_populates="creator")
    certificates = db.relationship(
        "Certificate",
        back_populates="user",
        foreign_keys="Certificate.user_id",
    )
    insights = db.relationship(
        "Insight",
        back_populates="target_user",
        foreign_keys="Insight.target_user_id",
    )
    audit_logs = db.relationship("AuditLog", back_populates="user")

    __table_args__ = (
        db.Index("ix_users_role_id", "role_id"),
        db.Index("ix_users_is_active", "is_active"),
    )

    def to_dict(self):
        return {
            "id": str(self.id),
            "username": self.username,
            "full_name": self.full_name,
            "email": self.email,
            "role_id": self.role_id,
            "mfa_enabled": self.mfa_enabled,
            "is_active": self.is_active,
            "is_blocked": self.is_blocked,
            "pd_consent_at": (
                self.pd_consent_at.isoformat() if self.pd_consent_at else None
            ),
            "anonymized_at": (
                self.anonymized_at.isoformat() if self.anonymized_at else None
            ),
            "failed_attempts": self.failed_attempts,
            "last_login_at": (
                self.last_login_at.isoformat() if self.last_login_at else None
            ),
            "password_changed_at": self.password_changed_at.isoformat(),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
