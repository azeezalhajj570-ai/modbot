"""add agent_leads table and agent safety fields

Revision ID: 20260430_0071
Revises: 20260430_0070
Create Date: 2026-04-30
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "20260430_0071"
down_revision: str = "20260430_0070"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("max_actions_per_hour", sa.Integer(), nullable=True))
    op.add_column("agents", sa.Column("min_delay_seconds", sa.Float(), nullable=True))
    op.add_column("agents", sa.Column("cooldown_minutes", sa.Integer(), nullable=True))
    op.add_column("agents", sa.Column("safety_mode_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False))
    op.add_column("agents", sa.Column("safety_mode_until", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "agent_leads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id", ondelete="CASCADE"), index=True, nullable=False),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), index=True, nullable=False),
        sa.Column("tg_user_id", sa.BigInteger(), index=True, nullable=True),
        sa.Column("username", sa.String(255), nullable=True),
        sa.Column("first_name", sa.String(255), nullable=True),
        sa.Column("last_name", sa.String(255), nullable=True),
        sa.Column("source_group_tg_id", sa.BigInteger(), nullable=True),
        sa.Column("source_group_title", sa.String(255), nullable=True),
        sa.Column("source_message_id", sa.BigInteger(), nullable=True),
        sa.Column("message_text", sa.Text(), nullable=True),
        sa.Column("lead_label", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), server_default="new", nullable=False),
        sa.Column("assigned_to", sa.BigInteger(), nullable=True),
        sa.Column("contact_info", sa.String(512), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), server_default="0.5", nullable=False),
        sa.Column("last_contacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("agent_id", "tg_user_id", "source_group_tg_id", name="uq_agent_lead_user_group"),
    )
    op.create_index("ix_agent_leads_status", "agent_leads", ["status"])
    op.create_index("ix_agent_leads_assigned_to", "agent_leads", ["assigned_to"])


def downgrade() -> None:
    op.drop_index("ix_agent_leads_assigned_to")
    op.drop_index("ix_agent_leads_status")
    op.drop_table("agent_leads")
    op.drop_column("agents", "safety_mode_until")
    op.drop_column("agents", "safety_mode_enabled")
    op.drop_column("agents", "cooldown_minutes")
    op.drop_column("agents", "min_delay_seconds")
    op.drop_column("agents", "max_actions_per_hour")
