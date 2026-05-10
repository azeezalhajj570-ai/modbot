"""add plan to subscription and promotion codes

Revision ID: c10851f4d769
Revises: b82c40b0b4a8
Create Date: 2026-04-26 00:38:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c10851f4d769'
down_revision = 'b82c40b0b4a8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('promotion_codes', sa.Column('plan', sa.String(length=32), nullable=False, server_default='pro'))
    op.add_column('subscription_requests', sa.Column('plan', sa.String(length=32), nullable=False, server_default='pro'))
    op.create_index(op.f('ix_subscription_requests_plan'), 'subscription_requests', ['plan'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_subscription_requests_plan'), table_name='subscription_requests')
    op.drop_column('subscription_requests', 'plan')
    op.drop_column('promotion_codes', 'plan')
