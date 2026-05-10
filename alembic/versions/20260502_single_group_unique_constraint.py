"""replace partial group indexes with single tg_group_id unique constraint

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-05-02
"""

from typing import Sequence, Union

from alembic import op

revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_groups_owner_tg_group_id")
    op.execute("DROP INDEX IF EXISTS uq_groups_unowned_tg_group_id")
    op.execute("CREATE UNIQUE INDEX uq_groups_tg_group_id ON groups (tg_group_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_groups_tg_group_id")
    op.execute("""
        CREATE UNIQUE INDEX uq_groups_owner_tg_group_id
        ON groups (owner_user_id, tg_group_id)
        WHERE owner_user_id IS NOT NULL
    """)
    op.execute("""
        CREATE UNIQUE INDEX uq_groups_unowned_tg_group_id
        ON groups (tg_group_id)
        WHERE owner_user_id IS NULL
    """)
