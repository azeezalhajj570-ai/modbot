"""merge max_messages_per_day

Revision ID: a460383d445c
Revises: a1b2c3d4e5f6, 491d639c069c
Create Date: 2026-05-02 18:10:45.694625
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a460383d445c'
down_revision = ('a1b2c3d4e5f6', '491d639c069c')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
