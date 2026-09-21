import enum

from ..core.extensions import db
from .mixins import BigIntPK, JSONB, UTCDateTime, pg_only, utcnow


class AlertSeverity(enum.Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertStatus(enum.Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class Alert(db.Model):
    __tablename__ = "alerts"

    id = db.Column(BigIntPK, primary_key=True)
    component = db.Column(db.String(64), nullable=False)
    severity = db.Column(
        db.Enum(AlertSeverity, name="alert_severity", native_enum=True),
        nullable=False,
        default=AlertSeverity.WARNING,
    )
    status = db.Column(
        db.Enum(AlertStatus, name="alert_status", native_enum=True),
        nullable=False,
        default=AlertStatus.OPEN,
    )
    title = db.Column(db.String(255), nullable=False)
    details = db.Column(JSONB, nullable=False, default=dict)

    fingerprint = db.Column(db.String(128), nullable=False)
    occurrences = db.Column(db.Integer, nullable=False, default=1)
    first_seen_at = db.Column(UTCDateTime(), nullable=False, default=utcnow)
    last_seen_at = db.Column(UTCDateTime(), nullable=False, default=utcnow)
    acknowledged_by = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("users.id", ondelete="SET NULL"),
    )
    acknowledged_at = db.Column(UTCDateTime())
    resolved_at = db.Column(UTCDateTime())

    acknowledger = db.relationship("User")

    __table_args__ = (
        db.Index("ix_alerts_status_severity", "status", "severity"),
        db.Index("ix_alerts_last_seen_at", "last_seen_at"),
        *pg_only(
            db.Index(
                "uq_alerts_open_fingerprint",
                "fingerprint",
                unique=True,
                postgresql_where=db.text("status <> 'RESOLVED'"),
            )
        ),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "component": self.component,
            "severity": self.severity.value,
            "status": self.status.value,
            "title": self.title,
            "details": self.details,
            "fingerprint": self.fingerprint,
            "occurrences": self.occurrences,
            "first_seen_at": self.first_seen_at.isoformat(),
            "last_seen_at": self.last_seen_at.isoformat(),
            "acknowledged_by": (
                str(self.acknowledged_by) if self.acknowledged_by else None
            ),
            "acknowledged_at": (
                self.acknowledged_at.isoformat() if self.acknowledged_at else None
            ),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }
