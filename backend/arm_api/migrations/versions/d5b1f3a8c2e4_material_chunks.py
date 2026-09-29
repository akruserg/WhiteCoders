"""База знаний: фрагменты загруженных материалов

Revision ID: d5b1f3a8c2e4
Revises: c4a9d2e7f1b3
"""

from alembic import op
import sqlalchemy as sa

revision = "d5b1f3a8c2e4"
down_revision = "c4a9d2e7f1b3"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "material_chunks" in sa.inspect(bind).get_table_names():
        return
    import arm_api.models  # noqa: F401
    from arm_api.models.material_chunk import MaterialChunk

    MaterialChunk.__table__.create(bind=bind, checkfirst=True)


def downgrade():
    op.drop_table("material_chunks")
