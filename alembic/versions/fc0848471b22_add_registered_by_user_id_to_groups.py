"""add_registered_by_user_id_to_groups

Revision ID: fc0848471b22
Revises: ccaf7435d13f
Create Date: 2026-05-02 12:14:39.808460
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fc0848471b22'
down_revision = 'f481f13f8074'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("groups", sa.Column("registered_by_user_id", sa.BigInteger(), nullable=True))
    op.create_index("ix_groups_registered_by_user_id", "groups", ["registered_by_user_id"])


def downgrade() -> None:
    op.drop_index("ix_groups_registered_by_user_id")
    op.drop_column("groups", "registered_by_user_id")
