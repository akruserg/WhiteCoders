"""Вид отчета «ошибки и сбои»

В PostgreSQL report_kind - нативный enum, новое значение добавляется командой
ALTER TYPE (в отдельной транзакции). В других СУБД ограничения на значение нет.

Revision ID: a8e4c6d2b9f3
Revises: f7d3b5c1e8a2
"""

from alembic import op

revision = "a8e4c6d2b9f3"
down_revision = "f7d3b5c1e8a2"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    with op.get_context().autocommit_block():
        # имена членов enum SQLAlchemy хранит в верхнем регистре
        op.execute("ALTER TYPE report_kind ADD VALUE IF NOT EXISTS 'SYSTEM_ERRORS'")


def downgrade():
    # значение enum в PostgreSQL удалить нельзя без пересоздания типа; оно безвредно
    pass
