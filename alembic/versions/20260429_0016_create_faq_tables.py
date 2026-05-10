"""create faq tables

Revision ID: 0016
Revises: 20260428_0020
Create Date: 2026-04-29 23:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0016"
down_revision: Union[str, None] = "20260428_0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "faq_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("safe_mode", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("default_mode", sa.String(length=32), nullable=False, server_default="admin_suggestion"),
        sa.Column("suggestion_threshold", sa.Float(), nullable=False, server_default=sa.text("3.0")),
        sa.Column("auto_reply_threshold", sa.Float(), nullable=False, server_default=sa.text("5.0")),
        sa.Column("max_replies_per_user_per_hour", sa.Integer(), nullable=False, server_default=sa.text("5")),
        sa.Column("max_replies_per_group_per_hour", sa.Integer(), nullable=False, server_default=sa.text("20")),
        sa.Column("answer_cooldown_seconds", sa.Integer(), nullable=False, server_default=sa.text("30")),
        sa.Column("log_unanswered_questions", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("require_admin_approved_sources", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id", name="uq_faq_settings_group_id"),
    )
    op.create_index("ix_faq_settings_group", "faq_settings", ["group_id"])

    op.create_table(
        "faq_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("keywords", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("language", sa.String(length=10), nullable=False, server_default=""),
        sa.Column("category", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("source_type", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("source_ref", sa.String(length=255), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("approved_by", sa.BigInteger(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("times_answered", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_faq_entries_group", "faq_entries", ["group_id"])
    op.create_index("ix_faq_entries_enabled", "faq_entries", ["enabled"])

    op.create_table(
        "faq_interactions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True, index=True),
        sa.Column("question_preview", sa.String(length=300), nullable=True),
        sa.Column("matched_faq_entry_id", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("mode", sa.String(length=32), nullable=True),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("answer_preview", sa.String(length=300), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="sent"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_faq_interactions_group", "faq_interactions", ["group_id"])
    op.create_index("ix_faq_interactions_created", "faq_interactions", ["created_at"])

    op.create_table(
        "unanswered_questions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True, index=True),
        sa.Column("question_preview", sa.String(length=300), nullable=False),
        sa.Column("normalized_question_hash", sa.String(length=64), nullable=False),
        sa.Column("frequency_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="new"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id", "normalized_question_hash", name="uq_unanswered_group_hash"),
    )
    op.create_index("ix_unanswered_group", "unanswered_questions", ["group_id"])
    op.create_index("ix_unanswered_status", "unanswered_questions", ["status"])


def downgrade() -> None:
    op.drop_table("unanswered_questions")
    op.drop_table("faq_interactions")
    op.drop_table("faq_entries")
    op.drop_table("faq_settings")
