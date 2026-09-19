from ..core.extensions import db

user_service_scope = db.Table(
    "user_service_scope",
    db.Column(
        "user_id",
        db.UUID(as_uuid=True),
        db.ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    db.Column(
        "category_id",
        db.Integer,
        db.ForeignKey("incident_categories.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    db.Index("ix_user_service_scope_category_id", "category_id"),
)


class IncidentCategory(db.Model):

    __tablename__ = "incident_categories"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(32), nullable=False, unique=True)
    name = db.Column(db.String(128), nullable=False)
    parent_id = db.Column(
        db.Integer,
        db.ForeignKey("incident_categories.id", ondelete="SET NULL"),
    )
    service_code = db.Column(db.String(64))
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    parent = db.relationship(
        "IncidentCategory",
        remote_side=[id],
        back_populates="children",
    )
    children = db.relationship(
        "IncidentCategory",
        back_populates="parent",
    )
    scoped_users = db.relationship(
        "User",
        secondary=user_service_scope,
        back_populates="service_scope",
        lazy="selectin",
    )
    scenarios = db.relationship("Scenario", back_populates="category")
    materials = db.relationship("Material", back_populates="category")
    grading_profiles = db.relationship("GradingProfile", back_populates="category")

    __table_args__ = (
        db.Index("ix_incident_categories_parent_id", "parent_id"),
        db.Index("ix_incident_categories_service_code", "service_code"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "parent_id": self.parent_id,
            "service_code": self.service_code,
            "is_active": self.is_active,
        }
