"""allow group-level agent notifications

Revision ID: 20260428_0020
Revises: f481f13f8074
Create Date: 2026-04-28 23:45:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260428_0020"
down_revision = "f481f13f8074"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("agent_notifications"):
        return

    with op.batch_alter_table("agent_notifications") as batch_op:
        batch_op.alter_column(
            "agent_id",
            existing_type=sa.Integer(),
            nullable=True,
            existing_nullable=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("agent_notifications"):
        return

    with op.batch_alter_table("agent_notifications") as batch_op:
        batch_op.alter_column(
            "agent_id",
            existing_type=sa.Integer(),
            nullable=False,
            existing_nullable=True,
        )
