"""add scraper tables

Revision ID: 20260413_0013
Revises: 20260410_0012
Create Date: 2026-04-13 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260413_0013"
down_revision = "20260410_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scraped_groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tg_group_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("group_type", sa.String(length=32), nullable=False),
        sa.Column("member_count", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scraped_groups_tg_group_id", "scraped_groups", ["tg_group_id"], unique=False)
    op.create_index("ix_scraped_groups_type", "scraped_groups", ["group_type"], unique=False)
    op.create_index("ix_scraped_groups_username", "scraped_groups", ["username"], unique=False)

    op.create_table(
        "scraped_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scraped_group_id", sa.Integer(), nullable=False),
        sa.Column("tg_group_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("sender_user_id", sa.BigInteger(), nullable=True),
        sa.Column("sender_username", sa.String(length=255), nullable=True),
        sa.Column("sender_first_name", sa.String(length=255), nullable=True),
        sa.Column("sender_last_name", sa.String(length=255), nullable=True),
        sa.Column("message_text", sa.Text(), nullable=True),
        sa.Column("message_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message_type", sa.String(length=32), nullable=False),
        sa.Column("media_file_id", sa.String(length=512), nullable=True),
        sa.Column("media_url", sa.String(length=1024), nullable=True),
        sa.Column("reply_to_message_id", sa.BigInteger(), nullable=True),
        sa.Column("forward_from_user_id", sa.BigInteger(), nullable=True),
        sa.Column("raw_data", sa.JSON(), nullable=False),
        sa.Column("scraped_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["scraped_group_id"], ["scraped_groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scraped_messages_tg_group_id", "scraped_messages", ["tg_group_id"], unique=False)
    op.create_index("ix_scraped_messages_message_id", "scraped_messages", ["tg_group_id", "message_id"], unique=True)
    op.create_index("ix_scraped_messages_sender_id", "scraped_messages", ["sender_user_id"], unique=False)
    op.create_index("ix_scraped_messages_date", "scraped_messages", ["message_date"], unique=False)

    op.create_table(
        "scraped_members",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scraped_group_id", sa.Integer(), nullable=False),
        sa.Column("tg_group_id", sa.BigInteger(), nullable=False),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("last_name", sa.String(length=255), nullable=True),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("is_bot", sa.Boolean(), nullable=False),
        sa.Column("is_premium", sa.Boolean(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=True),
        sa.Column("joined_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_data", sa.JSON(), nullable=False),
        sa.Column("scraped_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["scraped_group_id"], ["scraped_groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scraped_members_tg_group_id", "scraped_members", ["tg_group_id"], unique=False)
    op.create_index("ix_scraped_members_user_id", "scraped_members", ["tg_user_id"], unique=False)
    op.create_index("ix_scraped_members_group_user", "scraped_members", ["tg_group_id", "tg_user_id"], unique=True)
    op.create_index("ix_scraped_members_username", "scraped_members", ["username"], unique=False)


def downgrade() -> None:
    op.drop_table("scraped_members")
    op.drop_table("scraped_messages")
    op.drop_table("scraped_groups")
