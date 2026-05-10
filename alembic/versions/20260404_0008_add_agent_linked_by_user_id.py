"""add agent linked_by_user_id"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260404_0008"
down_revision = "20260403_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("linked_by_user_id", sa.BigInteger(), nullable=True))
    op.create_index(op.f("ix_agents_linked_by_user_id"), "agents", ["linked_by_user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_agents_linked_by_user_id"), table_name="agents")
    op.drop_column("agents", "linked_by_user_id")
