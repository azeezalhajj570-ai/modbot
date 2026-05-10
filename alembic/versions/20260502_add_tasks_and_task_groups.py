"""add tasks and task_groups tables, backfill from GroupSetting JSON

Revision ID: e1f2a3b4c5d6
Revises: d1e2f3a4b5c6
Create Date: 2026-05-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- tasks table ---
    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("assignment_id", sa.String(64), nullable=False),
        sa.Column("task_key", sa.String(100), nullable=False),
        sa.Column("executor_type", sa.String(16), nullable=False, server_default="bot"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("conditions", sa.JSON(), nullable=True),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("subscription_id", sa.Integer(), sa.ForeignKey("subscription_requests.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tasks_assignment_id", "tasks", ["assignment_id"], unique=True)
    op.create_index("ix_tasks_task_key", "tasks", ["task_key"])
    op.create_index("ix_tasks_executor_type", "tasks", ["executor_type"])
    op.create_index("ix_tasks_subscription_id", "tasks", ["subscription_id"])
    op.create_index("ix_tasks_agent_id", "tasks", ["agent_id"])

    # --- task_groups table ---
    op.create_table(
        "task_groups",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "group_id", name="uq_task_group"),
    )
    op.create_index("ix_task_groups_group_id", "task_groups", ["group_id"])

    # --- backfill from JSON in GroupSetting ---
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "group_settings" not in inspector.get_table_names():
        return

    result = conn.execute(
        sa.text("SELECT COUNT(*) FROM group_settings WHERE key = 'automation_tasks'")
    )
    if result.scalar() == 0:
        return

    # Extract tasks from the nested JSON stored in GroupSetting.value.
    # GroupSetting.value is json (not jsonb), so cast to jsonb for operators.
    # The JSON structure is: {"value": [{"assignment_id": "...", ...}, ...]}
    conn.execute(sa.text("""
        INSERT INTO tasks (assignment_id, task_key, executor_type, enabled, conditions, config, agent_id)
        SELECT DISTINCT ON (item->>'assignment_id')
            item->>'assignment_id'       AS assignment_id,
            item->>'task_key'            AS task_key,
            item->>'executor_type'       AS executor_type,
            COALESCE((item->>'enabled')::boolean, true) AS enabled,
            COALESCE(item->'conditions', '{}'::jsonb)   AS conditions,
            COALESCE(item->'config', '{}'::jsonb)       AS config,
            -- Only set agent_id if the referenced agent actually exists
            CASE
                WHEN (item->>'agent_id') IS NOT NULL
                     AND EXISTS (SELECT 1 FROM agents a WHERE a.id = (item->>'agent_id')::integer)
                THEN (item->>'agent_id')::integer
                ELSE NULL
            END AS agent_id
        FROM group_settings gs
        CROSS JOIN LATERAL jsonb_array_elements(
            CASE
                WHEN jsonb_typeof((gs.value #> '{value}')::jsonb) = 'array' THEN (gs.value #> '{value}')::jsonb
                WHEN jsonb_typeof(gs.value::jsonb) = 'array' THEN gs.value::jsonb
                ELSE '[]'::jsonb
            END
        ) AS item
        WHERE gs.key = 'automation_tasks'
          AND item->>'assignment_id' IS NOT NULL
          AND item->>'task_key' IS NOT NULL
          AND item->>'executor_type' IS NOT NULL
    """))

    # Backfill task_groups from the group_ids list in each task item.
    conn.execute(sa.text("""
        INSERT INTO task_groups (task_id, group_id)
        SELECT DISTINCT t.id, grp_id::integer
        FROM group_settings gs
        CROSS JOIN LATERAL jsonb_array_elements(
            CASE
                WHEN jsonb_typeof((gs.value #> '{value}')::jsonb) = 'array' THEN (gs.value #> '{value}')::jsonb
                WHEN jsonb_typeof(gs.value::jsonb) = 'array' THEN gs.value::jsonb
                ELSE '[]'::jsonb
            END
        ) AS item
        JOIN tasks t ON t.assignment_id = item->>'assignment_id'
        CROSS JOIN LATERAL jsonb_array_elements_text(
            CASE
                WHEN jsonb_typeof(item->'group_ids') = 'array' THEN item->'group_ids'
                WHEN item->>'group_id' IS NOT NULL THEN jsonb_build_array(item->>'group_id')
                ELSE '[]'::jsonb
            END
        ) AS grp_id
        WHERE gs.key = 'automation_tasks'
          AND grp_id IS NOT NULL
          AND grp_id != ''
        ON CONFLICT (task_id, group_id) DO NOTHING
    """))

    # Reset sequences
    conn.execute(sa.text(
        "SELECT setval('tasks_id_seq', COALESCE((SELECT MAX(id) FROM tasks), 1))"
    ))


def downgrade() -> None:
    op.drop_table("task_groups")
    op.drop_table("tasks")
