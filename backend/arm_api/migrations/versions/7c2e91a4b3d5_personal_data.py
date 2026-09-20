"""Персональные данные: согласие на обработку и отметка об обезличивании

Revision ID: 7c2e91a4b3d5
Revises: 451ea7e8d705
"""

from alembic import op
import sqlalchemy as sa

revision = "7c2e91a4b3d5"
down_revision = "451ea7e8d705"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("pd_consent_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("anonymized_at", sa.DateTime(timezone=True)))


def downgrade():
    op.drop_column("users", "anonymized_at")
    op.drop_column("users", "pd_consent_at")
