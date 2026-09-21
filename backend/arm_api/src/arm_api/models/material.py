import uuid

from ..core.extensions import db
from .mixins import UTCDateTime, utcnow


class Material(db.Model):
    __tablename__ = "materials"

    id = db.Column(
        db.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    title = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(64), nullable=False)
    file_path = db.Column(db.String(512), nullable=False)
    size_bytes = db.Column(db.BigInteger, nullable=False)
    checksum = db.Column(db.String(128))
    version = db.Column(db.SmallInteger, nullable=False, default=1)

    is_indexed = db.Column(db.Boolean, nullable=False, default=False)
    indexed_at = db.Column(UTCDateTime())
    category_id = db.Column(db.Integer, db.ForeignKey("incident_categories.id"))
    uploaded_by = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("users.id", ondelete="SET NULL"),
    )
    created_at = db.Column(UTCDateTime(), nullable=False, default=utcnow)

    category = db.relationship("IncidentCategory", back_populates="materials")
    uploader = db.relationship("User", back_populates="uploaded_materials")
    chunks = db.relationship(
        "MaterialChunk", back_populates="material", cascade="all, delete-orphan"
    )

    __table_args__ = (
        db.Index("ix_materials_category_id", "category_id"),
        db.Index("ix_materials_is_indexed", "is_indexed"),
    )

    def to_dict(self):
        return {
            "id": str(self.id),
            "title": self.title,
            "mime_type": self.mime_type,
            "file_path": self.file_path,
            "size_bytes": self.size_bytes,
            "checksum": self.checksum,
            "version": self.version,
            "is_indexed": self.is_indexed,
            "indexed_at": self.indexed_at.isoformat() if self.indexed_at else None,
            "category_id": self.category_id,
            "uploaded_by": str(self.uploaded_by) if self.uploaded_by else None,
            "created_at": self.created_at.isoformat(),
        }
