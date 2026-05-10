from __future__ import annotations

from sqlalchemy import select

from bot.automation.models import TaskAssignment
from bot.db.models import GroupSetting
from bot.services.group_service import canonical_tg_group_id
from bot.services.settings_service import SettingsService

TASKS_SETTING_KEY = "automation_tasks"


class TaskAssignmentStore:
    def __init__(self, session) -> None:
        self.session = session
        self.settings = SettingsService(session)

    async def list_assignments(self, group_id: int) -> list[TaskAssignment]:
        value = await self.settings.get_one(group_id, TASKS_SETTING_KEY)
        if not isinstance(value, list):
            return []

        assignments: list[TaskAssignment] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            task_key = str(item.get("task_key") or "").strip()
            executor_type = str(item.get("executor_type") or "").strip()
            assignment_id = str(item.get("assignment_id") or "").strip()
            if not task_key or not executor_type or not assignment_id:
                continue
            assignments.append(
                TaskAssignment(
                    assignment_id=assignment_id,
                    task_key=task_key,
                    executor_type=executor_type,
                    enabled=bool(item.get("enabled", True)),
                    conditions=dict(item.get("conditions") or {}),
                    config=dict(item.get("config") or {}),
                    agent_id=int(item["agent_id"]) if item.get("agent_id") is not None else None,
                    group_ids=[int(value) for value in list(item.get("group_ids") or []) if value not in {None, ""}],
                    group_tg_ids=[int(value) for value in list(item.get("group_tg_ids") or []) if value not in {None, ""}],
                    group_titles=[str(value).strip() for value in list(item.get("group_titles") or []) if str(value or "").strip()],
                )
            )
        return assignments

    async def save_assignments(self, group_id: int, assignments: list[TaskAssignment]) -> None:
        await self.settings.set_value(group_id, TASKS_SETTING_KEY, [self.serialize_assignment(item) for item in assignments])

    async def upsert_assignment(self, group_id: int, assignment: TaskAssignment) -> TaskAssignment:
        assignments = await self.list_assignments(group_id)
        for index, existing in enumerate(assignments):
            if existing.assignment_id == assignment.assignment_id:
                assignments[index] = assignment
                break
        else:
            assignments.append(assignment)
        await self.save_assignments(group_id, assignments)
        return assignment

    async def delete_assignment(self, group_id: int, assignment_id: str) -> bool:
        assignments = await self.list_assignments(group_id)
        filtered = [assignment for assignment in assignments if assignment.assignment_id != assignment_id]
        if len(filtered) == len(assignments):
            return False
        await self.save_assignments(group_id, filtered)
        return True

    async def find_agent_assignments_for_chat(self, chat_id: int) -> list[TaskAssignment]:
        _assignments: list[TaskAssignment] = []
        rows = (
            await self.session.execute(
                select(GroupSetting.group_id, GroupSetting.value)
                .where(GroupSetting.key == TASKS_SETTING_KEY)
            )
        ).all()
        canonical_chat_id = canonical_tg_group_id(int(chat_id))
        for row in rows:
            items = SettingsService.unwrap_value(row.value)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                executor_type = str(item.get("executor_type") or "").strip()
                if executor_type != "agent":
                    continue
                if not bool(item.get("enabled", True)):
                    continue
                assignment_id = str(item.get("assignment_id") or "").strip()
                task_key = str(item.get("task_key") or "").strip()
                if not task_key or not assignment_id:
                    continue
                group_tg_ids = [int(v) for v in list(item.get("group_tg_ids") or []) if v not in {None, ""}]
                if group_tg_ids:
                    if not any(canonical_tg_group_id(tg_id) == canonical_chat_id for tg_id in group_tg_ids):
                        continue
                _assignments.append(
                    TaskAssignment(
                        assignment_id=assignment_id,
                        task_key=task_key,
                        executor_type=executor_type,
                        enabled=True,
                        conditions=dict(item.get("conditions") or {}),
                        config=dict(item.get("config") or {}),
                        agent_id=int(item["agent_id"]) if item.get("agent_id") is not None else None,
                        group_ids=[int(v) for v in list(item.get("group_ids") or []) if v not in {None, ""}],
                        group_tg_ids=group_tg_ids,
                        group_titles=[str(v).strip() for v in list(item.get("group_titles") or []) if str(v or "").strip()],
                    )
                )
        return _assignments

    @staticmethod
    def serialize_assignment(assignment: TaskAssignment, *, group_id: int | None = None) -> dict[str, object]:
        return {
            "assignment_id": assignment.assignment_id,
            "task_key": assignment.task_key,
            "executor_type": assignment.executor_type,
            "enabled": assignment.enabled,
            "conditions": assignment.conditions,
            "config": assignment.config,
            "agent_id": assignment.agent_id,
            "group_id": group_id,
            "group_ids": list(assignment.group_ids),
            "group_tg_ids": list(assignment.group_tg_ids),
            "group_titles": list(assignment.group_titles),
        }
