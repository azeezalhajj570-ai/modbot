"""add agent auth fields

Revision ID: 20260310_0003
Revises: 20260310_0002
Create Date: 2026-03-10 00:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260310_0003"
down_revision = "20260310_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("phone_number", sa.String(length=32), nullable=True))
    op.add_column("agents", sa.Column("auth_state", sa.String(length=32), nullable=False, server_default="active"))
    op.add_column("agents", sa.Column("session_string", sa.Text(), nullable=True))
    op.add_column("agents", sa.Column("phone_code_hash", sa.String(length=255), nullable=True))
    op.create_index("ix_agents_phone_number", "agents", ["phone_number"], unique=False)
    op.create_index("ix_agents_auth_state", "agents", ["auth_state"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_agents_auth_state", table_name="agents")
    op.drop_index("ix_agents_phone_number", table_name="agents")
    op.drop_column("agents", "phone_code_hash")
    op.drop_column("agents", "session_string")
    op.drop_column("agents", "auth_state")
    op.drop_column("agents", "phone_number")
