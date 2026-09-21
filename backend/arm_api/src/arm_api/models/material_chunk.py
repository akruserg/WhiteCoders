from ..core.extensions import db


class MaterialChunk(db.Model):
    """Фрагмент текста загруженного материала (база знаний для ИИ)."""

    __tablename__ = "material_chunks"

    id = db.Column(db.BigInteger().with_variant(db.Integer, "sqlite"), primary_key=True)
    material_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("materials.id", ondelete="CASCADE"),
        nullable=False,
    )
    seq = db.Column(db.Integer, nullable=False)
    text = db.Column(db.Text, nullable=False)
    stems = db.Column(db.Text, nullable=False, default="")  # основы слов через пробел

    material = db.relationship("Material", back_populates="chunks")

    __table_args__ = (db.Index("ix_material_chunks_material_id", "material_id"),)
