"""add join request approvals table

Revision ID: 20260414_0015
Revises: 20260414_0014
Create Date: 2026-04-14 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260414_0015"
down_revision = "20260414_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_name = "join_request_approvals"

    if inspector.has_table(table_name):
        return

    op.create_table(
        table_name,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("protected_group_tg_id", sa.BigInteger(), nullable=False),
        sa.Column("user_tg_id", sa.BigInteger(), nullable=False),
        sa.Column("invite_link", sa.Text(), nullable=True),
        sa.Column("first_name", sa.String(255), nullable=True),
        sa.Column("username", sa.String(255), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("required_group_tg_ids", sa.Text(), nullable=True),
        sa.Column("verified_group_tg_ids", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_by", sa.BigInteger(), nullable=True),
        sa.Column("decline_reason", sa.Text(), nullable=True),
    )

    op.create_index(
        "ix_join_request_approvals_protected_group_tg_id",
        table_name,
        ["protected_group_tg_id"],
    )
    op.create_index(
        "ix_join_request_approvals_user_tg_id",
        table_name,
        ["user_tg_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_name = "join_request_approvals"

    if not inspector.has_table(table_name):
        return

    op.drop_index("ix_join_request_approvals_user_tg_id", table_name=table_name)
    op.drop_index("ix_join_request_approvals_protected_group_tg_id", table_name=table_name)
    op.drop_table(table_name)
