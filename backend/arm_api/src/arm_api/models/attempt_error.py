import enum

from ..core.extensions import db
from .mixins import BigIntPK


class ErrorKind(enum.Enum):
    CONTENT = "content"
    TIMING = "timing"
    GRAMMAR = "grammar"
    PROCEDURE = "procedure"
    MISSING = "missing"


class AttemptError(db.Model):
    __tablename__ = "attempt_errors"

    id = db.Column(BigIntPK, primary_key=True)
    attempt_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("attempts.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind = db.Column(
        db.Enum(ErrorKind, name="error_kind", native_enum=True),
        nullable=False,
    )
    field_key = db.Column(db.String(64))
    severity = db.Column(db.SmallInteger, nullable=False, default=1)
    message = db.Column(db.Text, nullable=False)
    expected = db.Column(db.Text)
    actual = db.Column(db.Text)
    position = db.Column(db.Integer)

    attempt = db.relationship("Attempt", back_populates="errors")

    __table_args__ = (
        db.Index("ix_attempt_errors_attempt_id", "attempt_id"),
        db.Index("ix_attempt_errors_kind_field", "kind", "field_key"),
        db.CheckConstraint(
            "severity BETWEEN 1 AND 5", name="ck_attempt_errors_severity"
        ),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "attempt_id": str(self.attempt_id),
            "kind": self.kind.value,
            "field_key": self.field_key,
            "severity": self.severity,
            "message": self.message,
            "expected": self.expected,
            "actual": self.actual,
            "position": self.position,
        }
