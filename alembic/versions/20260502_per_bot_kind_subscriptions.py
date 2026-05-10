"""update subscription unique constraint to per-bot_kind

Revision ID: b1c2d3e4f5a6
Revises: a460383d445c
Create Date: 2026-05-02
"""

from typing import Sequence, Union

from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "a460383d445c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS uq_subscription_requests_one_approved_per_tg_user;
        CREATE UNIQUE INDEX uq_subscription_requests_one_approved_per_tg_user_bot_kind
        ON subscription_requests (tg_user_id, bot_kind)
        WHERE status = 'approved';
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS uq_subscription_requests_one_approved_per_tg_user_bot_kind;
        CREATE UNIQUE INDEX uq_subscription_requests_one_approved_per_tg_user
        ON subscription_requests (tg_user_id)
        WHERE status = 'approved';
    """)
