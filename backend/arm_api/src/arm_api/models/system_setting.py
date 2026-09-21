import enum

from ..core.extensions import db
from .mixins import JSONB, UTCDateTime, utcnow


class SettingScope(enum.Enum):
    VOIP = "voip"
    BACKUP = "backup"
    LOGGING = "logging"
    SECURITY = "security"
    PERFORMANCE = "performance"
    AI = "ai"
    UI = "ui"


class SystemSetting(db.Model):
    __tablename__ = "system_settings"

    key = db.Column(db.String(128), primary_key=True)
    scope = db.Column(
        db.Enum(SettingScope, name="setting_scope", native_enum=True), nullable=False
    )
    value = db.Column(JSONB, nullable=False)
    default_value = db.Column(JSONB)
    description = db.Column(db.String(255))
    is_secret = db.Column(db.Boolean, nullable=False, default=False)
    requires_restart = db.Column(db.Boolean, nullable=False, default=False)
    updated_by = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("users.id", ondelete="SET NULL"),
    )
    updated_at = db.Column(
        UTCDateTime(), nullable=False, default=utcnow, onupdate=utcnow
    )

    editor = db.relationship("User")

    __table_args__ = (db.Index("ix_system_settings_scope", "scope"),)

    def to_dict(self, reveal_secret=False):
        return {
            "key": self.key,
            "scope": self.scope.value,
            "value": "***" if self.is_secret and not reveal_secret else self.value,
            "default_value": self.default_value,
            "description": self.description,
            "is_secret": self.is_secret,
            "requires_restart": self.requires_restart,
            "updated_by": str(self.updated_by) if self.updated_by else None,
            "updated_at": self.updated_at.isoformat(),
        }
