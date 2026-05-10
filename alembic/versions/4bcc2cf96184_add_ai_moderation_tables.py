"""add_ai_moderation_tables

Revision ID: 4bcc2cf96184
Revises: b82c40b0b4a8
Create Date: 2026-04-26 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4bcc2cf96184'
down_revision = 'c10851f4d769'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "moderation_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("safe_mode", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("default_action", sa.String(length=32), nullable=False, server_default="review"),
        sa.Column("review_threshold", sa.Float(), nullable=False, server_default="0.65"),
        sa.Column("auto_delete_threshold", sa.Float(), nullable=False, server_default="0.92"),
        sa.Column("mute_threshold", sa.Float(), nullable=False, server_default="0.95"),
        sa.Column("ban_threshold", sa.Float(), nullable=False, server_default="0.98"),
        sa.Column("action_for_arabic_ads", sa.String(length=32), nullable=True),
        sa.Column("action_for_investment_scam", sa.String(length=32), nullable=True),
        sa.Column("action_for_crypto_scam", sa.String(length=32), nullable=True),
        sa.Column("action_for_phishing_link", sa.String(length=32), nullable=True),
        sa.Column("action_for_link_spam", sa.String(length=32), nullable=True),
        sa.Column("action_for_repeated_promo", sa.String(length=32), nullable=True),
        sa.Column("allowlisted_domains", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("blocked_domains", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("allowlisted_user_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("muted_duration_seconds", sa.Integer(), nullable=False, server_default="3600"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("group_id", name="uq_moderation_settings_group"),
    )
    op.create_index("ix_moderation_settings_group_id", "moderation_settings", ["group_id"], unique=True)

    op.create_table(
        "moderation_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("text_preview", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("matched_signals", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("recommended_action", sa.String(length=32), nullable=False),
        sa.Column("action_taken", sa.String(length=32), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("group_id", "message_id", name="uq_moderation_event_group_message"),
    )
    op.create_index("ix_moderation_events_group_id", "moderation_events", ["group_id"], unique=False)
    op.create_index("ix_moderation_events_user_id", "moderation_events", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_table("moderation_events")
    op.drop_table("moderation_settings")
