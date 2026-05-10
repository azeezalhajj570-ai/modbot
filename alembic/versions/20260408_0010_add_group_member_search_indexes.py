"""add group member search indexes"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260408_0010"
down_revision = "20260404_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_group_members_lower_username",
        "group_members",
        [sa.text("lower(username)")],
        unique=False,
    )
    op.create_index(
        "ix_group_members_lower_full_name",
        "group_members",
        [sa.text("lower(full_name)")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_group_members_lower_full_name", table_name="group_members")
    op.drop_index("ix_group_members_lower_username", table_name="group_members")
