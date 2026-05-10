"""widen_owner_audit_actor_id

Revision ID: 8c0c57e9d7d2
Revises: 4d6cb1663c71
Create Date: 2026-04-01 22:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "8c0c57e9d7d2"
down_revision = "4d6cb1663c71"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("owner_audit_log") as batch_op:
            batch_op.alter_column(
                "actor_id",
                existing_type=sa.Integer(),
                type_=sa.BigInteger(),
                existing_nullable=False,
            )
        return

    op.alter_column(
        "owner_audit_log",
        "actor_id",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("owner_audit_log") as batch_op:
            batch_op.alter_column(
                "actor_id",
                existing_type=sa.BigInteger(),
                type_=sa.Integer(),
                existing_nullable=False,
            )
        return

    op.alter_column(
        "owner_audit_log",
        "actor_id",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
    )
