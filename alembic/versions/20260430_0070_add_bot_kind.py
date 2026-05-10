"""add bot_kind to subscription_requests and promotion_codes

Revision ID: 20260430_0070
Revises: 20260430_0050
Create Date: 2026-04-30
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "20260430_0070"
down_revision: str = "20260430_0050"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("subscription_requests", sa.Column("bot_kind", sa.String(16), nullable=True))
    op.create_index("ix_subscription_requests_bot_kind", "subscription_requests", ["bot_kind"])
    op.add_column("promotion_codes", sa.Column("bot_kind", sa.String(16), nullable=True))
    op.create_index("ix_promotion_codes_bot_kind", "promotion_codes", ["bot_kind"])


def downgrade() -> None:
    op.drop_index("ix_promotion_codes_bot_kind")
    op.drop_column("promotion_codes", "bot_kind")
    op.drop_index("ix_subscription_requests_bot_kind")
    op.drop_column("subscription_requests", "bot_kind")
