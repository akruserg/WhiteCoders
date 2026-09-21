"""Рабочие места (АРМ) и их XML-конфигурации

Revision ID: b3f8a1c4d6e2
Revises: 7c2e91a4b3d5
"""

from alembic import op
import sqlalchemy as sa

revision = "b3f8a1c4d6e2"
down_revision = "7c2e91a4b3d5"
branch_labels = None
depends_on = None


def upgrade():
    # на не-PostgreSQL или на базе, созданной после появления модели, таблица уже есть
    bind = op.get_bind()
    if "workstations" in sa.inspect(bind).get_table_names():
        return
    import arm_api.models  # noqa: F401
    from arm_api.models.workstation import Workstation

    Workstation.__table__.create(bind=bind, checkfirst=True)


def downgrade():
    op.drop_table("workstations")
