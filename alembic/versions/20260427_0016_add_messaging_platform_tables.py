"""add messaging platform tables

Revision ID: 20260427_0016
Revises: 4bcc2cf96184
Create Date: 2026-04-27 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260427_0016"
down_revision = "4bcc2cf96184"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))

    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("tg_user_id", existing_type=sa.BigInteger(), nullable=True)
        batch_op.create_index("ix_users_email", ["email"], unique=True)

    users_table = sa.table(
        "users",
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    op.execute(users_table.update().values(updated_at=sa.func.coalesce(users_table.c.created_at, sa.func.now())))
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("updated_at", existing_type=sa.DateTime(timezone=True), nullable=False)

    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("business_profile", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_tenants_owner_user_id", "tenants", ["owner_user_id"], unique=False)

    op.create_table(
        "channel_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("external_account_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="disconnected"),
        sa.Column("qr_code", sa.Text(), nullable=True),
        sa.Column("credentials_encrypted", sa.JSON(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "type", "display_name", name="uq_channel_accounts_tenant_type_display_name"),
    )
    op.create_index("ix_channel_accounts_tenant_id", "channel_accounts", ["tenant_id"], unique=False)
    op.create_index("ix_channel_accounts_type", "channel_accounts", ["type"], unique=False)
    op.create_index("ix_channel_accounts_status", "channel_accounts", ["status"], unique=False)

    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_account_id", sa.Integer(), sa.ForeignKey("channel_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_contact_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "channel_account_id", "external_contact_id", name="uq_contacts_tenant_channel_external_contact"),
    )
    op.create_index("ix_contacts_tenant_id", "contacts", ["tenant_id"], unique=False)
    op.create_index("ix_contacts_channel_account_id", "contacts", ["channel_account_id"], unique=False)

    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_account_id", sa.Integer(), sa.ForeignKey("channel_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("contact_id", sa.Integer(), sa.ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ai_active"),
        sa.Column("latest_message_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("unread_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "channel_account_id", "contact_id", name="uq_conversations_tenant_channel_contact"),
    )
    op.create_index("ix_conversations_tenant_id", "conversations", ["tenant_id"], unique=False)
    op.create_index("ix_conversations_channel_account_id", "conversations", ["channel_account_id"], unique=False)
    op.create_index("ix_conversations_channel", "conversations", ["channel"], unique=False)
    op.create_index("ix_conversations_status", "conversations", ["status"], unique=False)
    op.create_index("ix_conversations_last_message_at", "conversations", ["last_message_at"], unique=False)

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_account_id", sa.Integer(), sa.ForeignKey("channel_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("direction", sa.String(length=32), nullable=False),
        sa.Column("sender_type", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("external_message_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_messages_tenant_id", "messages", ["tenant_id"], unique=False)
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"], unique=False)
    op.create_index("ix_messages_channel_account_id", "messages", ["channel_account_id"], unique=False)
    op.create_index("ix_messages_created_at", "messages", ["created_at"], unique=False)

    op.create_table(
        "leads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=64), nullable=True),
        sa.Column("service", sa.String(length=255), nullable=True),
        sa.Column("preferred_time", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="new"),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="whatsapp"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_leads_tenant_id", "leads", ["tenant_id"], unique=False)
    op.create_index("ix_leads_conversation_id", "leads", ["conversation_id"], unique=False)
    op.create_index("ix_leads_status", "leads", ["status"], unique=False)
    op.create_index("ix_leads_created_at", "leads", ["created_at"], unique=False)

    op.create_table(
        "automations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("channel", sa.String(length=32), nullable=False, server_default="all"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_automations_tenant_slug"),
    )
    op.create_index("ix_automations_tenant_id", "automations", ["tenant_id"], unique=False)

    op.create_table(
        "skills",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("channel", sa.String(length=32), nullable=False, server_default="all"),
        sa.Column("input_schema", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("slug", name="uq_skills_slug"),
    )

    op.create_table(
        "skill_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("skill_id", sa.Integer(), sa.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("input", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_skill_runs_tenant_id", "skill_runs", ["tenant_id"], unique=False)
    op.create_index("ix_skill_runs_skill_id", "skill_runs", ["skill_id"], unique=False)
    op.create_index("ix_skill_runs_conversation_id", "skill_runs", ["conversation_id"], unique=False)
    op.create_index("ix_skill_runs_created_at", "skill_runs", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_skill_runs_created_at", table_name="skill_runs")
    op.drop_index("ix_skill_runs_conversation_id", table_name="skill_runs")
    op.drop_index("ix_skill_runs_skill_id", table_name="skill_runs")
    op.drop_index("ix_skill_runs_tenant_id", table_name="skill_runs")
    op.drop_table("skill_runs")
    op.drop_table("skills")
    op.drop_index("ix_automations_tenant_id", table_name="automations")
    op.drop_table("automations")
    op.drop_index("ix_leads_created_at", table_name="leads")
    op.drop_index("ix_leads_status", table_name="leads")
    op.drop_index("ix_leads_conversation_id", table_name="leads")
    op.drop_index("ix_leads_tenant_id", table_name="leads")
    op.drop_table("leads")
    op.drop_index("ix_messages_created_at", table_name="messages")
    op.drop_index("ix_messages_channel_account_id", table_name="messages")
    op.drop_index("ix_messages_conversation_id", table_name="messages")
    op.drop_index("ix_messages_tenant_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_conversations_last_message_at", table_name="conversations")
    op.drop_index("ix_conversations_status", table_name="conversations")
    op.drop_index("ix_conversations_channel", table_name="conversations")
    op.drop_index("ix_conversations_channel_account_id", table_name="conversations")
    op.drop_index("ix_conversations_tenant_id", table_name="conversations")
    op.drop_table("conversations")
    op.drop_index("ix_contacts_channel_account_id", table_name="contacts")
    op.drop_index("ix_contacts_tenant_id", table_name="contacts")
    op.drop_table("contacts")
    op.drop_index("ix_channel_accounts_status", table_name="channel_accounts")
    op.drop_index("ix_channel_accounts_type", table_name="channel_accounts")
    op.drop_index("ix_channel_accounts_tenant_id", table_name="channel_accounts")
    op.drop_table("channel_accounts")
    op.drop_index("ix_tenants_owner_user_id", table_name="tenants")
    op.drop_table("tenants")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_index("ix_users_email")
        batch_op.alter_column("tg_user_id", existing_type=sa.BigInteger(), nullable=False)
    op.drop_column("users", "updated_at")
    op.drop_column("users", "password_hash")
    op.drop_column("users", "email")
