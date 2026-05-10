"""add missing scraper tables conversations daily_summaries knowledge leads

Revision ID: ccaf7435d13f
Revises: 5ece8a21f18c
Create Date: 2026-04-30 22:29:32.638497
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ccaf7435d13f'
down_revision = '5ece8a21f18c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scraped_conversations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scraped_group_id", sa.Integer(), nullable=False),
        sa.Column("tg_group_id", sa.BigInteger(), nullable=False),
        sa.Column("root_message_id", sa.BigInteger(), nullable=True),
        sa.Column("root_message_text", sa.Text(), nullable=True),
        sa.Column("root_sender_user_id", sa.BigInteger(), nullable=True),
        sa.Column("root_sender_name", sa.String(255), nullable=True),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("participant_count", sa.Integer(), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("first_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_topic", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["scraped_group_id"], ["scraped_groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scraped_conv_group_id", "scraped_conversations", ["scraped_group_id"], unique=False)
    op.create_index("ix_scraped_conv_last_message", "scraped_conversations", ["last_message_at"], unique=False)

    op.create_table(
        "scraped_daily_summaries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scraped_group_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("active_users", sa.JSON(), nullable=True),
        sa.Column("top_topics", sa.JSON(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["scraped_group_id"], ["scraped_groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_daily_summaries_group_date", "scraped_daily_summaries", ["scraped_group_id", "date"], unique=True)

    op.create_table(
        "group_knowledge",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scraped_group_id", sa.Integer(), nullable=False),
        sa.Column("knowledge_type", sa.String(32), nullable=False),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("source_message_ids", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_updated", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["scraped_group_id"], ["scraped_groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_group_knowledge_type", "group_knowledge", ["knowledge_type"], unique=False)
    op.create_index("ix_group_knowledge_group", "group_knowledge", ["scraped_group_id"], unique=False)

    op.create_table(
        "scraped_leads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scraped_group_id", sa.Integer(), nullable=False),
        sa.Column("source_message_id", sa.BigInteger(), nullable=True),
        sa.Column("sender_user_id", sa.BigInteger(), nullable=True),
        sa.Column("sender_name", sa.String(255), nullable=True),
        sa.Column("signal", sa.String(64), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("contact_info", sa.String(512), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["scraped_group_id"], ["scraped_groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scraped_leads_group_id", "scraped_leads", ["scraped_group_id"], unique=False)
    op.create_index("ix_scraped_leads_status", "scraped_leads", ["status"], unique=False)


def downgrade() -> None:
    op.drop_table("scraped_leads")
    op.drop_table("group_knowledge")
    op.drop_table("scraped_daily_summaries")
    op.drop_table("scraped_conversations")
