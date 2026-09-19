import enum

from ..core.extensions import db
from .mixins import JSONB, utcnow


class ReportStatus(enum.Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class ReportKind(enum.Enum):
    SESSION = "session"
    STUDENT_PROGRESS = "student_progress"
    GROUP_PROGRESS = "group_progress"
    ERROR_HEATMAP = "error_heatmap"
    SYSTEM_USAGE = "system_usage"
    SECURITY_AUDIT = "security_audit"


class Report(db.Model):
    __tablename__ = "reports"

    id = db.Column(
        db.UUID(as_uuid=True),
        primary_key=True,
        server_default=db.text("gen_random_uuid()"),
    )
    kind = db.Column(
        db.Enum(ReportKind, name="report_kind", native_enum=True), nullable=False
    )
    format = db.Column(db.String(8), nullable=False)

    session_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("training_sessions.id", ondelete="CASCADE"),
    )
    params = db.Column(JSONB, nullable=False, default=dict)
    status = db.Column(
        db.Enum(ReportStatus, name="report_status", native_enum=True),
        nullable=False,
        default=ReportStatus.QUEUED,
    )
    file_path = db.Column(db.String(512))
    error = db.Column(db.Text)
    created_by = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("users.id", ondelete="SET NULL"),
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    ready_at = db.Column(db.DateTime(timezone=True))

    creator = db.relationship("User", back_populates="reports")
    session = db.relationship("TrainingSession", back_populates="reports")

    __table_args__ = (
        db.Index("ix_reports_session_id", "session_id"),
        db.Index("ix_reports_created_by", "created_by"),
        db.Index("ix_reports_status_created", "status", "created_at"),
        db.CheckConstraint(
            "format IN ('pdf', 'xlsx', 'csv', 'json')", name="ck_reports_format"
        ),
    )

    def to_dict(self):
        return {
            "id": str(self.id),
            "kind": self.kind.value,
            "format": self.format,
            "session_id": str(self.session_id) if self.session_id else None,
            "params": self.params,
            "status": self.status.value,
            "file_path": self.file_path,
            "error": self.error,
            "created_by": str(self.created_by) if self.created_by else None,
            "created_at": self.created_at.isoformat(),
            "ready_at": self.ready_at.isoformat() if self.ready_at else None,
        }
