"""add max_messages_per_day to agents

Revision ID: a1b2c3d4e5f6
Revises: f481f13f8074
Create Date: 2026-05-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f481f13f8074"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("max_messages_per_day", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("agents", "max_messages_per_day")
