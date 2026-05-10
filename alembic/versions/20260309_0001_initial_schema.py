"""initial schema

Revision ID: 20260309_0001
Revises: None
Create Date: 2026-03-09 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260309_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("language_code", sa.String(length=8), nullable=False, server_default="en"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_tg_user_id", "users", ["tg_user_id"], unique=True)
    op.create_index("ix_users_language_code", "users", ["language_code"], unique=False)

    op.create_table(
        "groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tg_group_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_groups_tg_group_id", "groups", ["tg_group_id"], unique=True)
    op.create_index("ix_groups_title", "groups", ["title"], unique=False)

    op.create_table(
        "group_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("group_id", "key", name="uq_group_setting_group_key"),
    )
    op.create_index("ix_group_settings_group_id", "group_settings", ["group_id"], unique=False)
    op.create_index("ix_group_settings_key", "group_settings", ["key"], unique=False)

    op.create_table(
        "admin_roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("group_id", "user_id", name="uq_group_admin_role"),
    )
    op.create_index("ix_admin_roles_group_id", "admin_roles", ["group_id"], unique=False)
    op.create_index("ix_admin_roles_user_id", "admin_roles", ["user_id"], unique=False)
    op.create_index("ix_admin_roles_role", "admin_roles", ["role"], unique=False)

    op.create_table(
        "plugins_enabled",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plugin_name", sa.String(length=100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.UniqueConstraint("group_id", "plugin_name", name="uq_group_plugin"),
    )
    op.create_index("ix_plugins_enabled_group_id", "plugins_enabled", ["group_id"], unique=False)
    op.create_index("ix_plugins_enabled_plugin_name", "plugins_enabled", ["plugin_name"], unique=False)

    op.create_table(
        "moderation_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_user_id", sa.BigInteger(), nullable=True),
        sa.Column("admin_user_id", sa.BigInteger(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_moderation_logs_group_id", "moderation_logs", ["group_id"], unique=False)
    op.create_index("ix_moderation_logs_action", "moderation_logs", ["action"], unique=False)
    op.create_index("ix_moderation_logs_target_user_id", "moderation_logs", ["target_user_id"], unique=False)
    op.create_index("ix_moderation_logs_admin_user_id", "moderation_logs", ["admin_user_id"], unique=False)

    op.create_table(
        "warnings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("issued_by", sa.BigInteger(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_warnings_group_id", "warnings", ["group_id"], unique=False)
    op.create_index("ix_warnings_user_id", "warnings", ["user_id"], unique=False)
    op.create_index("ix_warnings_issued_by", "warnings", ["issued_by"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_warnings_issued_by", table_name="warnings")
    op.drop_index("ix_warnings_user_id", table_name="warnings")
    op.drop_index("ix_warnings_group_id", table_name="warnings")
    op.drop_table("warnings")

    op.drop_index("ix_moderation_logs_admin_user_id", table_name="moderation_logs")
    op.drop_index("ix_moderation_logs_target_user_id", table_name="moderation_logs")
    op.drop_index("ix_moderation_logs_action", table_name="moderation_logs")
    op.drop_index("ix_moderation_logs_group_id", table_name="moderation_logs")
    op.drop_table("moderation_logs")

    op.drop_index("ix_plugins_enabled_plugin_name", table_name="plugins_enabled")
    op.drop_index("ix_plugins_enabled_group_id", table_name="plugins_enabled")
    op.drop_table("plugins_enabled")

    op.drop_index("ix_admin_roles_role", table_name="admin_roles")
    op.drop_index("ix_admin_roles_user_id", table_name="admin_roles")
    op.drop_index("ix_admin_roles_group_id", table_name="admin_roles")
    op.drop_table("admin_roles")

    op.drop_index("ix_group_settings_key", table_name="group_settings")
    op.drop_index("ix_group_settings_group_id", table_name="group_settings")
    op.drop_table("group_settings")

    op.drop_index("ix_groups_title", table_name="groups")
    op.drop_index("ix_groups_tg_group_id", table_name="groups")
    op.drop_table("groups")

    op.drop_index("ix_users_language_code", table_name="users")
    op.drop_index("ix_users_tg_user_id", table_name="users")
    op.drop_table("users")
