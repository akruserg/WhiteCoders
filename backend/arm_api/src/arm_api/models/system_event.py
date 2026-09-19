from ..core.extensions import db
from .mixins import JSONB, utcnow


class SystemEvent(db.Model):
    __tablename__ = "system_events"

    id = db.Column(db.BigInteger, primary_key=True)
    ts = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    component = db.Column(db.String(64), nullable=False)
    level = db.Column(db.String(16), nullable=False)
    message = db.Column(db.Text, nullable=False)
    details = db.Column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        db.Index("ix_system_events_ts", "ts"),
        db.Index("ix_system_events_component_level", "component", "level"),
        db.CheckConstraint(
            "level IN ('debug', 'info', 'warning', 'error', 'critical')",
            name="ck_system_events_level",
        ),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "ts": self.ts.isoformat(),
            "component": self.component,
            "level": self.level,
            "message": self.message,
            "details": self.details,
        }
