"""add_paid_group_access_tables

Revision ID: 39535420799c
Revises: 4bcc2cf96184
Create Date: 2026-04-26 13:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '39535420799c'
down_revision = '4bcc2cf96184'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Group Subscription Settings
    op.create_table(
        "group_subscription_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("payment_mode", sa.String(length=32), nullable=False, server_default="manual_payment"),
        sa.Column("default_currency", sa.String(length=8), nullable=False, server_default="USD"),
        sa.Column("auto_approve_manual_payments", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("auto_remove_expired", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("expiry_action", sa.String(length=32), nullable=False, server_default="review"),
        sa.Column("grace_period_days", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("reminder_days_before_expiry", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("invite_link_expire_seconds", sa.Integer(), nullable=False, server_default="86400"),
        sa.Column("invite_link_member_limit", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("payment_instructions", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("group_id", name="uq_group_subscription_settings_group"),
    )
    op.create_index("ix_group_subscription_settings_group_id", "group_subscription_settings", ["group_id"], unique=True)

    # 2. Subscription Plans
    op.create_table(
        "group_subscription_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price_amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="USD"),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_group_subscription_plans_group_id", "group_subscription_plans", ["group_id"], unique=False)

    # 3. Group Subscribers
    op.create_table(
        "group_subscribers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("group_subscription_plans.id", ondelete="SET NULL"), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_provider", sa.String(length=32), nullable=True),
        sa.Column("payment_reference", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_group_subscribers_group_id", "group_subscribers", ["group_id"], unique=False)
    op.create_index("ix_group_subscribers_user_id", "group_subscribers", ["user_id"], unique=False)
    op.create_index("ix_group_subscribers_status", "group_subscribers", ["status"], unique=False)
    
    op.create_index(
        "uq_group_subscribers_active_one_per_user",
        "group_subscribers",
        ["group_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('active', 'pending')"),
        sqlite_where=sa.text("status IN ('active', 'pending')"),
    )

    # 4. Payment Records
    op.create_table(
        "group_payment_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("group_subscription_plans.id", ondelete="SET NULL"), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("provider_reference", sa.String(length=255), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", "provider_reference", name="uq_payment_provider_ref"),
    )
    op.create_index("ix_group_payment_records_group_id", "group_payment_records", ["group_id"], unique=False)
    op.create_index("ix_group_payment_records_user_id", "group_payment_records", ["user_id"], unique=False)
    op.create_index("ix_group_payment_records_status", "group_payment_records", ["status"], unique=False)
    op.create_index("ix_group_payment_records_provider_reference", "group_payment_records", ["provider_reference"], unique=False)

    # 5. Subscription Events
    op.create_table(
        "group_subscription_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_group_subscription_events_group_id", "group_subscription_events", ["group_id"], unique=False)
    op.create_index("ix_group_subscription_events_user_id", "group_subscription_events", ["user_id"], unique=False)
    op.create_index("ix_group_subscription_events_event_type", "group_subscription_events", ["event_type"], unique=False)


def downgrade() -> None:
    op.drop_table("group_subscription_events")
    op.drop_table("group_payment_records")
    op.drop_table("group_subscribers")
    op.drop_table("group_subscription_plans")
    op.drop_table("group_subscription_settings")
