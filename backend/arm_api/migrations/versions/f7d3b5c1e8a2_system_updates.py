"""История пакетных обновлений

Revision ID: f7d3b5c1e8a2
Revises: e6c2a4b9d7f1
"""

from alembic import op
import sqlalchemy as sa

revision = "f7d3b5c1e8a2"
down_revision = "e6c2a4b9d7f1"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "system_updates" in sa.inspect(bind).get_table_names():
        return
    import arm_api.models  # noqa: F401
    from arm_api.models.system_update import SystemUpdate

    SystemUpdate.__table__.create(bind=bind, checkfirst=True)


def downgrade():
    op.drop_table("system_updates")
