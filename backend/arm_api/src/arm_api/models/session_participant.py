from ..core.extensions import db


class SessionParticipant(db.Model):
    __tablename__ = "session_participants"

    session_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("training_sessions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    joined_at = db.Column(db.DateTime(timezone=True))
    left_at = db.Column(db.DateTime(timezone=True))

    session = db.relationship("TrainingSession", back_populates="participants")
    user = db.relationship("User", back_populates="session_participations")

    __table_args__ = (db.Index("ix_session_participants_user_id", "user_id"),)

    def to_dict(self):
        return {
            "session_id": str(self.session_id),
            "user_id": str(self.user_id),
            "joined_at": self.joined_at.isoformat() if self.joined_at else None,
            "left_at": self.left_at.isoformat() if self.left_at else None,
        }
