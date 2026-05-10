"""add private access requirements

Revision ID: 20260403_0007
Revises: 20260403_0006
Create Date: 2026-04-03 00:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260403_0007"
down_revision = "20260403_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "private_access_requirements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("required_group_tg_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("required_group_tg_id", name="uq_private_access_requirement"),
    )
    op.create_index(
        op.f("ix_private_access_requirements_required_group_tg_id"),
        "private_access_requirements",
        ["required_group_tg_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_private_access_requirements_required_group_tg_id"), table_name="private_access_requirements")
    op.drop_table("private_access_requirements")
