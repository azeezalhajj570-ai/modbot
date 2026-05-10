from __future__ import annotations

from dataclasses import dataclass

from bot.automation.models import TaskAssignment, TaskDefinition, TaskEvent
from bot.automation.registry import Registry
from bot.db.models import AgentJob


@dataclass
class AgentTaskBinding:
    assignment: TaskAssignment
    task: TaskDefinition
    event: TaskEvent


class AgentTaskStore:
    def __init__(self, registry: Registry) -> None:
        self.registry = registry

    def load(self, job: AgentJob) -> AgentTaskBinding | None:
        if job.job_type != "automation_task":
            return None

        payload = dict(job.job_payload or {})
        task_key = str(payload.get("task_key") or "").strip()
        if not task_key:
            return None

        raw_event = dict(payload.get("event") or {})
        event = TaskEvent(
            name=str(raw_event.get("name") or "message.received"),
            group_id=int(raw_event["group_id"]),
            user_id=int(raw_event["user_id"]) if raw_event.get("user_id") is not None else None,
            payload=dict(raw_event.get("payload") or {}),
        )
        assignment = TaskAssignment(
            assignment_id=str(payload.get("assignment_id") or f"agent-job-{job.id}"),
            task_key=task_key,
            executor_type="agent",
            enabled=True,
            config=dict(payload.get("task_config") or {}),
            conditions=dict(payload.get("conditions") or {}),
            agent_id=job.agent_id,
        )
        return AgentTaskBinding(assignment=assignment, task=self.registry.get(task_key), event=event)
