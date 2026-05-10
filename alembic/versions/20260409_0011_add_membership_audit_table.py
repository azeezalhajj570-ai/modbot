"""add membership audit table"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260409_0011"
down_revision = "20260408_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "membership_audit",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("group_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("requested_by", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False, server_default="add"),
        sa.Column("result", sa.String(length=32), nullable=False),
        sa.Column("flood_wait_sec", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_membership_audit_group_id", "membership_audit", ["group_id"], unique=False)
    op.create_index("idx_membership_audit_user_id", "membership_audit", ["user_id"], unique=False)
    op.create_index("idx_membership_audit_created_at", "membership_audit", [sa.text("created_at DESC")], unique=False)


def downgrade() -> None:
    op.drop_index("idx_membership_audit_created_at", table_name="membership_audit")
    op.drop_index("idx_membership_audit_user_id", table_name="membership_audit")
    op.drop_index("idx_membership_audit_group_id", table_name="membership_audit")
    op.drop_table("membership_audit")
