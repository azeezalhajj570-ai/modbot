"""add agent notifications

Revision ID: 20260423_0009
Revises: 20260423_0008
Create Date: 2026-04-23 00:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260423_0009"
down_revision = "20260414_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("agent_notifications"):
        return

    op.create_table(
        "agent_notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False, server_default="info"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("is_seen", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_notifications_agent_id", "agent_notifications", ["agent_id"], unique=False)
    op.create_index("ix_agent_notifications_group_id", "agent_notifications", ["group_id"], unique=False)
    op.create_index("ix_agent_notifications_kind", "agent_notifications", ["kind"], unique=False)
    op.create_index("ix_agent_notifications_is_seen", "agent_notifications", ["is_seen"], unique=False)
    op.create_index("ix_agent_notifications_created_at", "agent_notifications", ["created_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("agent_notifications"):
        return
    op.drop_index("ix_agent_notifications_created_at", table_name="agent_notifications")
    op.drop_index("ix_agent_notifications_is_seen", table_name="agent_notifications")
    op.drop_index("ix_agent_notifications_kind", table_name="agent_notifications")
    op.drop_index("ix_agent_notifications_group_id", table_name="agent_notifications")
    op.drop_index("ix_agent_notifications_agent_id", table_name="agent_notifications")
    op.drop_table("agent_notifications")
