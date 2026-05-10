"""add notification settings and events

Revision ID: 20260427_0018
Revises: 20260427_0017
Create Date: 2026-04-27 23:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260427_0018"
down_revision = "20260427_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("notify_on_new_lead", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("notify_on_needs_human", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("daily_summary_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("notification_channel", sa.String(length=32), nullable=False, server_default="none"),
        sa.Column("notification_target", sa.String(length=1024), nullable=True),
        sa.Column("quiet_hours", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", name="uq_notification_settings_tenant"),
    )
    op.create_index("ix_notification_settings_tenant_id", "notification_settings", ["tenant_id"], unique=False)

    op.create_table(
        "notification_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("channel", sa.String(length=32), nullable=False, server_default="none"),
        sa.Column("target", sa.String(length=1024), nullable=True),
        sa.Column("related_conversation_id", sa.Integer(), sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("related_lead_id", sa.Integer(), sa.ForeignKey("leads.id", ondelete="SET NULL"), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_notification_events_tenant_id", "notification_events", ["tenant_id"], unique=False)
    op.create_index("ix_notification_events_type", "notification_events", ["type"], unique=False)
    op.create_index("ix_notification_events_status", "notification_events", ["status"], unique=False)
    op.create_index("ix_notification_events_channel", "notification_events", ["channel"], unique=False)
    op.create_index("ix_notification_events_related_conversation_id", "notification_events", ["related_conversation_id"], unique=False)
    op.create_index("ix_notification_events_related_lead_id", "notification_events", ["related_lead_id"], unique=False)
    op.create_index("ix_notification_events_created_at", "notification_events", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_notification_events_created_at", table_name="notification_events")
    op.drop_index("ix_notification_events_related_lead_id", table_name="notification_events")
    op.drop_index("ix_notification_events_related_conversation_id", table_name="notification_events")
    op.drop_index("ix_notification_events_channel", table_name="notification_events")
    op.drop_index("ix_notification_events_status", table_name="notification_events")
    op.drop_index("ix_notification_events_type", table_name="notification_events")
    op.drop_index("ix_notification_events_tenant_id", table_name="notification_events")
    op.drop_table("notification_events")
    op.drop_index("ix_notification_settings_tenant_id", table_name="notification_settings")
    op.drop_table("notification_settings")
