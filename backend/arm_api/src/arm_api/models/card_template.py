from ..core.extensions import db
from .mixins import JSONB, utcnow


class CardTemplate(db.Model):
    __tablename__ = "card_templates"

    id = db.Column(
        db.UUID(as_uuid=True),
        primary_key=True,
        server_default=db.text("gen_random_uuid()"),
    )
    code = db.Column(db.String(64), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    version = db.Column(db.SmallInteger, nullable=False, default=1)
    fields = db.Column(JSONB, nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    scenarios = db.relationship("Scenario", back_populates="template")

    __table_args__ = (
        db.UniqueConstraint("code", "version", name="uq_card_templates_code_version"),
        db.Index(
            "uq_card_templates_active_code",
            "code",
            unique=True,
            postgresql_where=db.text("is_active"),
        ),
    )

    def to_dict(self):
        return {
            "id": str(self.id),
            "code": self.code,
            "name": self.name,
            "version": self.version,
            "fields": self.fields,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
        }
