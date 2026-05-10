"""add stripe_price_id to group_subscription_plans

Revision ID: 20260429_0030
Revises: f481f13f8074
Create Date: 2026-04-30
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "20260429_0030"
down_revision: Union[str, None] = "f481f13f8074"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("group_subscription_plans", sa.Column("stripe_price_id", sa.String(255), nullable=True))
    op.create_index("ix_group_subscription_plans_stripe_price", "group_subscription_plans", ["stripe_price_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_group_subscription_plans_stripe_price")
    op.drop_column("group_subscription_plans", "stripe_price_id")
