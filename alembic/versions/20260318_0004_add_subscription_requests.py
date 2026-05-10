"""add subscription requests

Revision ID: 20260318_0004
Revises: 20260310_0003
Create Date: 2026-03-18 00:00:00
"""

from alembic import op
import sqlalchemy as sa

revision = "20260318_0004"
down_revision = "20260310_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscription_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("language_code", sa.String(length=8), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column("response_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_subscription_requests_tg_user_id", "subscription_requests", ["tg_user_id"])
    op.create_index("ix_subscription_requests_status", "subscription_requests", ["status"])


def downgrade() -> None:
    op.drop_index("ix_subscription_requests_status", table_name="subscription_requests")
    op.drop_index("ix_subscription_requests_tg_user_id", table_name="subscription_requests")
    op.drop_table("subscription_requests")
