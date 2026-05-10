"""add reply_to_top_id to scraped_messages

Revision ID: 5ece8a21f18c
Revises: de1df38b6d5c
Create Date: 2026-04-30 22:10:16.020382
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5ece8a21f18c'
down_revision = 'de1df38b6d5c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scraped_messages", sa.Column("reply_to_top_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("scraped_messages", "reply_to_top_id")
