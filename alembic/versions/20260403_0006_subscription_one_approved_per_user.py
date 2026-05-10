"""subscription: one approved row per telegram user

Revision ID: 20260403_0006
Revises: 8c0c57e9d7d2
Create Date: 2026-04-03 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260403_0006"
down_revision = "8c0c57e9d7d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            WITH ranked AS (
              SELECT id,
                     ROW_NUMBER() OVER (PARTITION BY tg_user_id ORDER BY id DESC) AS rn
              FROM subscription_requests
              WHERE status = 'approved'
            )
            UPDATE subscription_requests
            SET status = 'superseded',
                response = CASE
                  WHEN response IS NULL OR TRIM(response) = '' THEN 'Superseded by a newer approved request.'
                  ELSE response
                END
            WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
            """
        )
    )
    op.create_index(
        "uq_subscription_requests_one_approved_per_tg_user",
        "subscription_requests",
        ["tg_user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'approved'"),
        sqlite_where=sa.text("status = 'approved'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_subscription_requests_one_approved_per_tg_user",
        table_name="subscription_requests",
    )
