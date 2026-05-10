"""add accounts and account_groups tables, backfill from agents

Uses explicit IDs matching the source agents table so that
account_groups backfill can join reliably.

Revision ID: d1e2f3a4b5c6
Revises: c2d3e4f5a6b7
Create Date: 2026-05-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- accounts table ---
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("subscription_id", sa.Integer(), sa.ForeignKey("subscription_requests.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("phone_number", sa.String(32), nullable=True),
        sa.Column("external_account_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("auth_state", sa.String(32), nullable=False, server_default="active"),
        sa.Column("session_string", sa.Text(), nullable=True),
        sa.Column("phone_code_hash", sa.String(255), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("max_actions_per_hour", sa.Integer(), nullable=True),
        sa.Column("max_messages_per_day", sa.Integer(), nullable=True),
        sa.Column("min_delay_seconds", sa.Float(), nullable=True),
        sa.Column("cooldown_minutes", sa.Integer(), nullable=True),
        sa.Column("safety_mode_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("safety_mode_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subscription_id", "external_account_id", name="uq_account_subscription_external_id"),
    )
    op.create_index("ix_accounts_phone_number", "accounts", ["phone_number"])
    op.create_index("ix_accounts_telegram_user_id", "accounts", ["telegram_user_id"])
    op.create_index("ix_accounts_status", "accounts", ["status"])
    op.create_index("ix_accounts_auth_state", "accounts", ["auth_state"])

    # --- account_groups table ---
    op.create_table(
        "account_groups",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="member"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "group_id", name="uq_account_group"),
    )
    op.create_index("ix_account_groups_group_id", "account_groups", ["group_id"])

    # --- backfill: copy existing agents into accounts ---
    # Use the same IDs as the source agents so the account_groups join is reliable.
    # The agents table may not exist in fresh DBs — that's fine, the SELECT
    # against a non-existent table simply inserts zero rows.
    # Resolve linked_by_user_id -> active subscription.
    op.execute("""
        INSERT INTO accounts (
            id, subscription_id,
            telegram_user_id, phone_number, external_account_id,
            status, auth_state, session_string, phone_code_hash, metadata,
            max_actions_per_hour, max_messages_per_day,
            min_delay_seconds, cooldown_minutes,
            safety_mode_enabled, safety_mode_until,
            created_at, updated_at
        )
        SELECT
            a.id,
            sr.id AS subscription_id,
            a.telegram_user_id, a.phone_number, a.external_account_id,
            a.status, a.auth_state, a.session_string, a.phone_code_hash, a.metadata,
            a.max_actions_per_hour, a.max_messages_per_day,
            a.min_delay_seconds, a.cooldown_minutes,
            a.safety_mode_enabled, a.safety_mode_until,
            a.created_at, a.updated_at
        FROM agents a
        LEFT JOIN subscription_requests sr
            ON sr.tg_user_id = a.linked_by_user_id
            AND sr.status = 'approved'
    """)

    # Reset the auto-increment sequence past the backfilled IDs.
    op.execute("""
        SELECT setval('accounts_id_seq', COALESCE((SELECT MAX(id) FROM accounts), 1))
    """)

    # Backfill account_groups from each agent's group_id.
    op.execute("""
        INSERT INTO account_groups (account_id, group_id, role)
        SELECT a.id, a.group_id, 'member'
        FROM agents a
        WHERE a.group_id IS NOT NULL
    """)


def downgrade() -> None:
    op.drop_table("account_groups")
    op.drop_table("accounts")
