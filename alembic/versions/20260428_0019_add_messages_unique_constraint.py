"""add unique constraint on messages external_message_id

Revision ID: 20260428_0019
Revises: 20260427_0018
Create Date: 2026-04-28 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260428_0019"
down_revision = "20260427_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("messages") as batch_op:
        batch_op.create_unique_constraint(
            "uq_messages_tenant_channel_external",
            ["tenant_id", "channel_account_id", "external_message_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("messages") as batch_op:
        batch_op.drop_constraint("uq_messages_tenant_channel_external", type_="unique")
