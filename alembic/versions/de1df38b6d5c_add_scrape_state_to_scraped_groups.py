"""add scrape_state to scraped_groups

Revision ID: de1df38b6d5c
Revises: 20260430_0071
Create Date: 2026-04-30 22:02:18.464617
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'de1df38b6d5c'
down_revision = '20260430_0071'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scraped_groups", sa.Column("scrape_state", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("scraped_groups", "scrape_state")
