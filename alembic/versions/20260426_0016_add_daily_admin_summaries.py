"""add daily admin summaries

Revision ID: 20260426_0016
Revises: 20260423_0009
Create Date: 2026-04-26 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260426_0016"
down_revision = "c10851f4d769"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("group_summary_settings"):
        op.create_table(
            "group_summary_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("summary_time", sa.String(length=5), nullable=False, server_default="21:00"),
            sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Asia/Aden"),
            sa.Column("delivery_mode", sa.String(length=32), nullable=False, server_default="dashboard_only"),
            sa.Column("admin_chat_id", sa.BigInteger(), nullable=True),
            sa.Column("include_top_users", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("include_links", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("include_moderation_events", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("include_unanswered_questions", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("include_recommendations", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("max_message_samples", sa.Integer(), nullable=False, server_default="500"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("group_id", name="uq_group_summary_settings_group_id"),
        )
        op.create_index("ix_group_summary_settings_group_id", "group_summary_settings", ["group_id"], unique=False)

    if not inspector.has_table("daily_group_summaries"):
        op.create_table(
            "daily_group_summaries",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
            sa.Column("summary_date", sa.Date(), nullable=False),
            sa.Column("total_messages", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("active_users_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("links_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("suspicious_messages_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("deleted_messages_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("top_users", sa.JSON(), nullable=False),
            sa.Column("top_topics", sa.JSON(), nullable=False),
            sa.Column("important_questions", sa.JSON(), nullable=False),
            sa.Column("unanswered_questions", sa.JSON(), nullable=False),
            sa.Column("links", sa.JSON(), nullable=False),
            sa.Column("moderation_highlights", sa.JSON(), nullable=False),
            sa.Column("recommendations", sa.JSON(), nullable=False),
            sa.Column("summary_text", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="generated"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("group_id", "summary_date", name="uq_daily_group_summary_group_date"),
        )
        op.create_index("ix_daily_group_summaries_group_id", "daily_group_summaries", ["group_id"], unique=False)
        op.create_index("ix_daily_group_summaries_summary_date", "daily_group_summaries", ["summary_date"], unique=False)
        op.create_index(
            "ix_daily_group_summary_group_created",
            "daily_group_summaries",
            ["group_id", "created_at"],
            unique=False,
        )

    if not inspector.has_table("group_message_activity"):
        op.create_table(
            "group_message_activity",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
            sa.Column("message_id", sa.BigInteger(), nullable=False),
            sa.Column("user_id", sa.BigInteger(), nullable=True),
            sa.Column("username", sa.String(length=255), nullable=True),
            sa.Column("text_preview", sa.String(length=300), nullable=True),
            sa.Column("normalized_text", sa.String(length=300), nullable=True),
            sa.Column("has_link", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("link_domains", sa.JSON(), nullable=False),
            sa.Column("is_question", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("is_forwarded", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("reply_to_message_id", sa.BigInteger(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("group_id", "message_id", name="uq_group_message_activity_group_message"),
        )
        op.create_index("ix_group_message_activity_group_id", "group_message_activity", ["group_id"], unique=False)
        op.create_index("ix_group_message_activity_message_id", "group_message_activity", ["message_id"], unique=False)
        op.create_index("ix_group_message_activity_user_id", "group_message_activity", ["user_id"], unique=False)
        op.create_index("ix_group_message_activity_created_at", "group_message_activity", ["created_at"], unique=False)
        op.create_index(
            "ix_group_message_activity_group_created",
            "group_message_activity",
            ["group_id", "created_at"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("group_message_activity"):
        op.drop_index("ix_group_message_activity_group_created", table_name="group_message_activity")
        op.drop_index("ix_group_message_activity_created_at", table_name="group_message_activity")
        op.drop_index("ix_group_message_activity_user_id", table_name="group_message_activity")
        op.drop_index("ix_group_message_activity_message_id", table_name="group_message_activity")
        op.drop_index("ix_group_message_activity_group_id", table_name="group_message_activity")
        op.drop_table("group_message_activity")

    if inspector.has_table("daily_group_summaries"):
        op.drop_index("ix_daily_group_summary_group_created", table_name="daily_group_summaries")
        op.drop_index("ix_daily_group_summaries_summary_date", table_name="daily_group_summaries")
        op.drop_index("ix_daily_group_summaries_group_id", table_name="daily_group_summaries")
        op.drop_table("daily_group_summaries")

    if inspector.has_table("group_summary_settings"):
        op.drop_index("ix_group_summary_settings_group_id", table_name="group_summary_settings")
        op.drop_table("group_summary_settings")
