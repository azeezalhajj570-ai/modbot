"""add group access requirements

Revision ID: 20260401_0005
Revises: 20260318_0004
Create Date: 2026-04-01 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260401_0005"
down_revision = "20260318_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_name = "group_access_requirements"
    existing_indexes = {index["name"] for index in inspector.get_indexes(table_name)} if inspector.has_table(table_name) else set()

    if not inspector.has_table(table_name):
        op.create_table(
            table_name,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("protected_group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
            sa.Column("required_group_tg_id", sa.BigInteger(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("protected_group_id", "required_group_tg_id", name="uq_group_access_requirement"),
        )
        existing_indexes = set()

    if "ix_group_access_requirements_protected_group_id" not in existing_indexes:
        op.create_index(
            "ix_group_access_requirements_protected_group_id",
            table_name,
            ["protected_group_id"],
        )
    if "ix_group_access_requirements_required_group_tg_id" not in existing_indexes:
        op.create_index(
            "ix_group_access_requirements_required_group_tg_id",
            table_name,
            ["required_group_tg_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_name = "group_access_requirements"
    if not inspector.has_table(table_name):
        return

    existing_indexes = {index["name"] for index in inspector.get_indexes(table_name)}
    if "ix_group_access_requirements_required_group_tg_id" in existing_indexes:
        op.drop_index(
            "ix_group_access_requirements_required_group_tg_id",
            table_name=table_name,
        )
    if "ix_group_access_requirements_protected_group_id" in existing_indexes:
        op.drop_index(
            "ix_group_access_requirements_protected_group_id",
            table_name=table_name,
        )
    op.drop_table(table_name)
