"""Лимит времени необязателен у занятия и сценария

Приоритет при выдаче карточки: занятие, сценарий, профиль оценивания, 30 с.
Раньше столбцы были NOT NULL с 30 по умолчанию, и лимит занятия всегда
перекрывал лимит сценария и профиля.

Revision ID: c4a9d2e7f1b3
Revises: b3f8a1c4d6e2
"""

from alembic import op
import sqlalchemy as sa

revision = "c4a9d2e7f1b3"
down_revision = "b3f8a1c4d6e2"
branch_labels = None
depends_on = None


def _set_nullable(nullable):
    inspector = sa.inspect(op.get_bind())
    for table in ("training_sessions", "scenarios"):
        column = next(
            c for c in inspector.get_columns(table) if c["name"] == "time_limit_sec"
        )
        if column["nullable"] == nullable:
            continue
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                "time_limit_sec", existing_type=sa.Integer(), nullable=nullable
            )


def upgrade():
    _set_nullable(True)


def downgrade():
    for table in ("training_sessions", "scenarios"):
        op.execute(f"UPDATE {table} SET time_limit_sec = 30 WHERE time_limit_sec IS NULL")
    _set_nullable(False)
