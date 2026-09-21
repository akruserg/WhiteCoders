"""Прогноз балла на момент выдачи карточки (сравнение прогноза с фактом)

Revision ID: e6c2a4b9d7f1
Revises: d5b1f3a8c2e4
"""

from alembic import op
import sqlalchemy as sa

revision = "e6c2a4b9d7f1"
down_revision = "d5b1f3a8c2e4"
branch_labels = None
depends_on = None


def upgrade():
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("attempts")}
    if "forecast_score" not in have:
        op.add_column("attempts", sa.Column("forecast_score", sa.Numeric(5, 2)))


def downgrade():
    op.drop_column("attempts", "forecast_score")
