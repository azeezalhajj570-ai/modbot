"""add message status for ai receptionist

Revision ID: 20260427_0017
Revises: 20260427_0016
Create Date: 2026-04-27 00:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260427_0017"
down_revision = "20260427_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("status", sa.String(length=32), nullable=True, server_default="sent"))
    op.create_index("ix_messages_status", "messages", ["status"], unique=False)

    messages_table = sa.table(
        "messages",
        sa.column("direction", sa.String(length=32)),
        sa.column("status", sa.String(length=32)),
    )
    op.execute(
        messages_table.update().values(
            status=sa.case(
                (messages_table.c.direction == "inbound", "sent"),
                else_="sent",
            )
        )
    )

    with op.batch_alter_table("messages") as batch_op:
        batch_op.alter_column("status", existing_type=sa.String(length=32), nullable=False, server_default="sent")


def downgrade() -> None:
    op.drop_index("ix_messages_status", table_name="messages")
    op.drop_column("messages", "status")
