"""scope group uniqueness by owner

Revision ID: 20260410_0012
Revises: 20260409_0011
Create Date: 2026-04-10 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260410_0012"
down_revision = "20260409_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_groups_tg_group_id", table_name="groups")
    op.create_index("ix_groups_tg_group_id", "groups", ["tg_group_id"], unique=False)
    op.create_index(
        "uq_groups_owner_tg_group_id",
        "groups",
        ["owner_user_id", "tg_group_id"],
        unique=True,
        postgresql_where=sa.text("owner_user_id IS NOT NULL"),
        sqlite_where=sa.text("owner_user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_groups_unowned_tg_group_id",
        "groups",
        ["tg_group_id"],
        unique=True,
        postgresql_where=sa.text("owner_user_id IS NULL"),
        sqlite_where=sa.text("owner_user_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_groups_unowned_tg_group_id", table_name="groups")
    op.drop_index("uq_groups_owner_tg_group_id", table_name="groups")
    op.drop_index("ix_groups_tg_group_id", table_name="groups")
    op.create_index("ix_groups_tg_group_id", "groups", ["tg_group_id"], unique=True)
