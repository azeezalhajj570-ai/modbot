"""add group members"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260404_0009"
down_revision = "20260404_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "group_members",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id", "tg_user_id", name="uq_group_member_group_tg_user"),
    )
    op.create_index(op.f("ix_group_members_group_id"), "group_members", ["group_id"], unique=False)
    op.create_index(op.f("ix_group_members_tg_user_id"), "group_members", ["tg_user_id"], unique=False)
    op.create_index(op.f("ix_group_members_role"), "group_members", ["role"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_group_members_role"), table_name="group_members")
    op.drop_index(op.f("ix_group_members_tg_user_id"), table_name="group_members")
    op.drop_index(op.f("ix_group_members_group_id"), table_name="group_members")
    op.drop_table("group_members")
