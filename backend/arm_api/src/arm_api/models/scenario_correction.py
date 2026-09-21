import uuid

from ..core.extensions import db
from .mixins import JSONB, UTCDateTime, utcnow


class ScenarioCorrection(db.Model):
    __tablename__ = "scenario_corrections"

    id = db.Column(
        db.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    scenario_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("scenarios.id", ondelete="CASCADE"),
        nullable=False,
    )
    author_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("users.id", ondelete="SET NULL"),
    )
    comment = db.Column(db.Text, nullable=False)
    applied = db.Column(db.Boolean, nullable=False, default=False)
    applied_at = db.Column(UTCDateTime())
    result = db.Column(JSONB)
    created_at = db.Column(UTCDateTime(), nullable=False, default=utcnow)

    scenario = db.relationship("Scenario", back_populates="corrections")
    author = db.relationship("User", back_populates="scenario_corrections")

    __table_args__ = (db.Index("ix_scenario_corrections_scenario_id", "scenario_id"),)

    def to_dict(self):
        return {
            "id": str(self.id),
            "scenario_id": str(self.scenario_id),
            "author_id": str(self.author_id) if self.author_id else None,
            "comment": self.comment,
            "applied": self.applied,
            "applied_at": self.applied_at.isoformat() if self.applied_at else None,
            "result": self.result,
            "created_at": self.created_at.isoformat(),
        }
