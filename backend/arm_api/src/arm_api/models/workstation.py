import uuid

from ..core.extensions import db
from .mixins import JSONB, UTCDateTime, utcnow


class Workstation(db.Model):
    """Рабочее место (АРМ) учебного класса и его настройки."""

    __tablename__ = "workstations"

    id = db.Column(db.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    number = db.Column(db.Integer, nullable=False, unique=True)
    name = db.Column(db.String(128), nullable=False)
    ip = db.Column(db.String(64))
    location = db.Column(db.String(255))
    user_id = db.Column(
        db.UUID(as_uuid=True), db.ForeignKey("users.id", ondelete="SET NULL")
    )
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    config = db.Column(JSONB, nullable=False, default=dict)
    created_at = db.Column(UTCDateTime(), nullable=False, default=utcnow)
    updated_at = db.Column(
        UTCDateTime(), nullable=False, default=utcnow, onupdate=utcnow
    )

    user = db.relationship("User")

    def to_dict(self):
        return {
            "id": str(self.id),
            "number": self.number,
            "name": self.name,
            "ip": self.ip,
            "location": self.location,
            "user_id": str(self.user_id) if self.user_id else None,
            "username": self.user.username if self.user else None,
            "is_active": self.is_active,
            "config": self.config,
            "updated_at": self.updated_at.isoformat(),
        }
