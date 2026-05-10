"""add last agent to scraped groups

Revision ID: 20260414_0014
Revises: 20260413_0013
Create Date: 2026-04-14 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260414_0014"
down_revision = "20260413_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("scraped_groups")}
    if "last_agent_id" in columns:
        return

    op.add_column("scraped_groups", sa.Column("last_agent_id", sa.Integer(), nullable=True))
    op.create_index("ix_scraped_groups_last_agent_id", "scraped_groups", ["last_agent_id"], unique=False)
    with op.batch_alter_table("scraped_groups") as batch_op:
        batch_op.create_foreign_key(
            "fk_scraped_groups_last_agent_id",
            "agents",
            ["last_agent_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("scraped_groups") as batch_op:
        batch_op.drop_constraint("fk_scraped_groups_last_agent_id", type_="foreignkey")
    op.drop_index("ix_scraped_groups_last_agent_id", table_name="scraped_groups")
    op.drop_column("scraped_groups", "last_agent_id")
