"""add agents and agent_jobs

Revision ID: 20260310_0002
Revises: 20260309_0001
Create Date: 2026-03-10 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260310_0002"
down_revision = "20260309_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_account_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("group_id", "external_account_id", name="uq_agent_group_external_account"),
    )
    op.create_index("ix_agents_group_id", "agents", ["group_id"], unique=False)
    op.create_index("ix_agents_external_account_id", "agents", ["external_account_id"], unique=False)
    op.create_index("ix_agents_status", "agents", ["status"], unique=False)
    op.create_index("ix_agents_telegram_user_id", "agents", ["telegram_user_id"], unique=False)

    op.create_table(
        "agent_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_type", sa.String(length=100), nullable=False),
        sa.Column("job_payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_jobs_agent_id", "agent_jobs", ["agent_id"], unique=False)
    op.create_index("ix_agent_jobs_job_type", "agent_jobs", ["job_type"], unique=False)
    op.create_index("ix_agent_jobs_status", "agent_jobs", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_agent_jobs_status", table_name="agent_jobs")
    op.drop_index("ix_agent_jobs_job_type", table_name="agent_jobs")
    op.drop_index("ix_agent_jobs_agent_id", table_name="agent_jobs")
    op.drop_table("agent_jobs")

    op.drop_index("ix_agents_telegram_user_id", table_name="agents")
    op.drop_index("ix_agents_status", table_name="agents")
    op.drop_index("ix_agents_external_account_id", table_name="agents")
    op.drop_index("ix_agents_group_id", table_name="agents")
    op.drop_table("agents")
