from ..core.extensions import db
from .mixins import utcnow

group_members = db.Table(
    "group_members",
    db.Column(
        "group_id",
        db.UUID(as_uuid=True),
        db.ForeignKey("groups.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    db.Column(
        "user_id",
        db.UUID(as_uuid=True),
        db.ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    db.Index("ix_group_members_user_id", "user_id"),
)


class Group(db.Model):
    __tablename__ = "groups"

    id = db.Column(
        db.UUID(as_uuid=True),
        primary_key=True,
        server_default=db.text("gen_random_uuid()"),
    )
    name = db.Column(db.String(128), nullable=False)
    teacher_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("users.id", ondelete="SET NULL"),
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    teacher = db.relationship(
        "User",
        back_populates="taught_groups",
        foreign_keys=[teacher_id],
    )
    members = db.relationship(
        "User",
        secondary=group_members,
        back_populates="groups",
        lazy="selectin",
    )
    sessions = db.relationship("TrainingSession", back_populates="group")
    insights = db.relationship(
        "Insight",
        back_populates="target_group",
        foreign_keys="Insight.target_group_id",
    )

    __table_args__ = (db.Index("ix_groups_teacher_id", "teacher_id"),)

    def to_dict(self):
        return {
            "id": str(self.id),
            "name": self.name,
            "teacher_id": str(self.teacher_id) if self.teacher_id else None,
            "created_at": self.created_at.isoformat(),
            "members": [str(user.id) for user in self.members],
        }
