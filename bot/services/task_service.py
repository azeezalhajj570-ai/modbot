from __future__ import annotations

from typing import Any
from uuid import uuid4
import structlog

from sqlalchemy import select

from bot.agents.service import AgentService
from bot.automation.conditions import ConditionEvaluator
from bot.automation.engine import TaskEngine
from bot.automation.executors import AgentJobExecutor, BotTaskExecutor
from bot.automation.models import TaskAssignment, TaskEvent
from bot.automation.registry import build_default_registry
from bot.core.runtime.automation import AutomationRuntimeService
from bot.db.models import Agent, Group
from bot.services.group_service import canonical_tg_group_id
from bot.services.notify_destination_approval_service import NotifyDestinationApprovalService
from bot.services.permission_service import PermissionService
from bot.services.task_activity_service import TaskActivityService
from bot.services.task_assignment_store import TaskAssignmentStore


logger = structlog.get_logger(__name__)


class TaskService:
    def __init__(
        self,
        session,
        *,
        dispatch_agent_job: Any,
        dispatch_follow_up: Any | None = None,
        dispatch_delete_message: Any | None = None,
        rate_limiter: Any | None = None,
        rate_limit_per_group_minute: int | None = None,
    ) -> None:
        self.session = session
        self.dispatch_agent_job = dispatch_agent_job
        self.dispatch_follow_up = dispatch_follow_up
        self.dispatch_delete_message = dispatch_delete_message
        self._rate_limiter = rate_limiter
        self._rate_limit_per_group_minute = rate_limit_per_group_minute
        self.registry = build_default_registry()
        self.store = TaskAssignmentStore(session)

    async def _ensure_group_admin(self, group_id: int, actor_user_id: int) -> None:
        can_manage = await PermissionService(self.session).can(group_id, actor_user_id, "group.settings.update")
        if not can_manage:
            raise PermissionError("User does not have permission to manage tasks for this group")

    async def _ensure_group_exists(self, group_id: int) -> None:
        group = await self._get_group(group_id)
        if group is None:
            raise ValueError("Group not found")

    async def list_catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "key": definition.key,
                "title": definition.title,
                "description": definition.description,
                "trigger": definition.trigger,
                "task_trigger": {"event_name": definition.trigger_rule.event_name} if definition.trigger_rule is not None else None,
                "planner": definition.planner_key,
                "action_template": {
                    "kind": definition.action_template.kind,
                    "metadata": dict(definition.action_template.metadata),
                } if definition.action_template is not None else None,
                "config_schema": definition.config_schema,
            }
            for definition in self.registry.list()
        ]

    async def list_assignments(self, *, actor_user_id: int, group_id: int) -> list[dict[str, Any]]:
        await self._ensure_group_admin(group_id, actor_user_id)
        bound_group = await self._get_group(group_id)
        return [self._dump_assignment(assignment, group=bound_group) for assignment in await self.store.list_assignments(group_id)]

    async def save_assignment(
        self,
        *,
        actor_user_id: int,
        group_id: int,
        task_key: str,
        executor_type: str,
        enabled: bool = True,
        conditions: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
        agent_id: int | None = None,
        assignment_id: str | None = None,
        group_ids: list[int] | None = None,
        group_tg_ids: list[int] | None = None,
        group_titles: list[str] | None = None,
    ) -> dict[str, Any]:
        await self._ensure_group_admin(group_id, actor_user_id)
        await self._ensure_group_exists(group_id)
        self.registry.get(task_key)
        if executor_type not in {"bot", "agent"}:
            raise ValueError("executor_type must be bot or agent")
        if executor_type == "agent" and agent_id is None:
            raise ValueError("agent_id is required for agent tasks")
        if agent_id is not None:
            agent = (await self.session.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
            if agent is None:
                raise ValueError("Assigned agent was not found")
            if executor_type == "agent" and agent_id is not None:
                if agent.linked_by_user_id is not None and int(agent.linked_by_user_id) != int(actor_user_id):
                    raise ValueError("Assigned agent does not belong to your account")

        bound_group = await self._get_group(group_id)
        normalized = TaskAssignment(
            assignment_id=assignment_id or uuid4().hex,
            task_key=task_key,
            executor_type=executor_type,
            enabled=enabled,
            conditions=dict(conditions or {}),
            config=dict(config or {}),
            agent_id=agent_id,
            group_ids=self._normalize_group_ids(group_ids, group_id=group_id),
            group_tg_ids=self._normalize_group_tg_ids(group_tg_ids, bound_group=bound_group),
            group_titles=self._normalize_group_titles(group_titles, bound_group=bound_group),
        )

        await self.store.upsert_assignment(group_id, normalized)
        return self._dump_assignment(normalized, group=bound_group)

    async def delete_assignment(self, *, actor_user_id: int, group_id: int, assignment_id: str) -> bool:
        await self._ensure_group_admin(group_id, actor_user_id)
        return await self.store.delete_assignment(group_id, assignment_id)

    async def handle_event(self, *, event_name: str, group_id: int, user_id: int | None, payload: dict[str, Any]) -> list[dict[str, Any]]:
        assignments = await self.store.list_assignments(group_id)
        chat_id = int(payload.get("chat_id") or 0)
        if chat_id:
            agent_assignments = await self.store.find_agent_assignments_for_chat(chat_id)
            seen_ids = {a.assignment_id for a in assignments}
            for a in agent_assignments:
                if a.assignment_id not in seen_ids:
                    assignments.append(a)
                    seen_ids.add(a.assignment_id)
        return await self._handle_event_with_assignments(
            assignments=assignments,
            event_name=event_name,
            group_id=group_id,
            user_id=user_id,
            payload=payload,
        )

    async def handle_agent_message_event(
        self,
        *,
        group_id: int,
        agent_id: int,
        source_chat_id: int,
        user_id: int | None,
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        assignments = await self.store.list_assignments(group_id)
        bound_group = await self._get_group(group_id)
        canonical_source_chat_id = canonical_tg_group_id(int(source_chat_id))
        filtered_assignments = [
            assignment
            for assignment in assignments
            if assignment.executor_type == "agent"
            and assignment.agent_id == int(agent_id)
            and (
                any(canonical_tg_group_id(int(group_tg_id)) == canonical_source_chat_id for group_tg_id in assignment.group_tg_ids)
                or (
                    not assignment.group_tg_ids
                    and bound_group is not None
                    and canonical_tg_group_id(int(bound_group.tg_group_id)) == canonical_source_chat_id
                )
            )
        ]
        return await self._handle_event_with_assignments(
            assignments=filtered_assignments,
            event_name="message.received",
            group_id=group_id,
            user_id=user_id,
            payload=payload,
        )

    async def _handle_event_with_assignments(
        self,
        *,
        assignments: list[TaskAssignment],
        event_name: str,
        group_id: int,
        user_id: int | None,
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not assignments:
            return []

        event = TaskEvent(name=event_name, group_id=group_id, user_id=user_id, payload=payload)
        engine = TaskEngine(
            registry=self.registry,
            condition_evaluator=ConditionEvaluator(),
            rate_limiter=self._rate_limiter,
            rate_limit_per_group_minute=self._rate_limit_per_group_minute,
        )
        executors = {
            "bot": BotTaskExecutor(
                dispatch_delete_message=self.dispatch_delete_message,
                automation_runtime=AutomationRuntimeService(self.session, dispatch_delete_message=self.dispatch_delete_message),
            ),
            "agent": AgentJobExecutor(AgentService(self.session), self.dispatch_agent_job),
        }
        results = await engine.process(assignments, event, executors)
        activity_service = TaskActivityService(self.session)
        approval_service = NotifyDestinationApprovalService(self.session)
        normalized_results: list[dict[str, Any]] = []
        for result in results:
            output = result.output
            approval_request = output.get("approval_request")
            if isinstance(approval_request, dict):
                if payload.get("bot") is None:
                    raise ValueError("Bot instance is required to send approval requests")
                target_user_id = approval_request.get("target_user_id")
                if target_user_id is None:
                    raise ValueError("Approval requests require target_user_id")
                logger.info(
                    "notify_destination_prompt_dispatching_via_bot",
                    group_id=group_id,
                    assignment_id=result.assignment.assignment_id,
                    task_key=result.assignment.task_key,
                    executor_type=result.assignment.executor_type,
                    destination=str(approval_request.get("chat_id", group_id)),
                    target_user_id=int(target_user_id),
                )
                await approval_service.create_prompt(
                    group_id=group_id,
                    assignment_id=result.assignment.assignment_id,
                    task_key=result.assignment.task_key,
                    agent_id=result.assignment.agent_id,
                    destination=approval_request.get("chat_id", group_id),
                    prompt_text=str(approval_request.get("prompt_text") or "").strip(),
                    private_reply_text=str(approval_request.get("private_reply_text") or "").strip(),
                    target_user_id=int(target_user_id),
                    source_group_title=str(approval_request.get("source_group_title") or "").strip(),
                    original_message_text=str(approval_request.get("original_message_text") or "").strip(),
                    source_chat_id=approval_request.get("source_chat_id"),
                    source_message_id=approval_request.get("source_message_id"),
                    bot=payload["bot"],
                )
            metadata = dict(output.get("metadata") or {})
            if result.assignment.executor_type == "bot":
                if metadata:
                    await activity_service.log_task_execution(
                        group_id=group_id,
                        target_user_id=user_id,
                        task_key=result.assignment.task_key,
                        assignment_id=result.assignment.assignment_id,
                        metadata=metadata,
                        reason=str(metadata.get("lead_label") or metadata.get("capture_type") or ""),
                    )
                follow_up = output.get("follow_up")
                if self.dispatch_follow_up and isinstance(follow_up, dict):
                    delay_seconds = int(follow_up.get("delay_seconds") or 0)
                    if delay_seconds > 0:
                        self.dispatch_follow_up(
                            delay_seconds=delay_seconds,
                            group_id=group_id,
                            chat_id=int(payload.get("chat_id", group_id)),
                            executor_type="bot",
                            agent_id=None,
                            text=str(follow_up.get("text") or ""),
                            assignment_id=result.assignment.assignment_id,
                            task_key=result.assignment.task_key,
                            target_user_id=user_id,
                            delete_after_seconds=int(follow_up.get("delete_after_seconds") or 0),
                        )
                        await activity_service.log_follow_up_scheduled(
                            group_id=group_id,
                            target_user_id=user_id,
                            task_key=result.assignment.task_key,
                            assignment_id=result.assignment.assignment_id,
                            delay_seconds=delay_seconds,
                        )
            normalized_results.append(output)
        return normalized_results

    async def handle_message_event(self, *, group_id: int, user_id: int | None, payload: dict[str, Any]) -> list[dict[str, Any]]:
        return await self.handle_event(event_name="message.received", group_id=group_id, user_id=user_id, payload=payload)

    async def handle_member_join_event(self, *, group_id: int, user_id: int | None, payload: dict[str, Any]) -> list[dict[str, Any]]:
        return await self.handle_event(event_name="member.joined", group_id=group_id, user_id=user_id, payload=payload)

    async def _load_assignments(self, group_id: int) -> list[TaskAssignment]:
        return await self.store.list_assignments(group_id)

    async def _get_group(self, group_id: int) -> Group | None:
        return (await self.session.execute(select(Group).where(Group.id == group_id))).scalar_one_or_none()

    async def _can_assign_agent_to_group(
        self,
        *,
        actor_user_id: int,
        agent: Agent,
        group_id: int,
    ) -> bool:
        if int(agent.group_id) == int(group_id):
            return True
        if agent.auth_state != "active" or not agent.session_string:
            return False
        target_group = await self._get_group(group_id)
        if target_group is None:
            return False
        target_tg_group_id = canonical_tg_group_id(int(target_group.tg_group_id))
        managed_groups = await AgentService(self.session).list_managed_member_groups(
            actor_user_id=actor_user_id,
            agent_id=agent.id,
        )
        return any(
            group.get("tg_group_id") is not None
            and canonical_tg_group_id(int(group["tg_group_id"])) == target_tg_group_id
            for group in managed_groups
        )

    async def _ensure_agent_group_bindings(
        self,
        *,
        actor_user_id: int,
        agent: Agent,
        owning_group_id: int,
        group_tg_ids: list[int] | None,
    ) -> None:
        normalized_group_tg_ids = [
            canonical_tg_group_id(int(group_tg_id))
            for group_tg_id in (group_tg_ids or [])
            if group_tg_id not in {None, ""}
        ]
        if not normalized_group_tg_ids:
            return
        allowed_group_tg_ids: set[int] = set()
        owning_group = await self._get_group(owning_group_id)
        if owning_group is not None:
            allowed_group_tg_ids.add(canonical_tg_group_id(int(owning_group.tg_group_id)))
        if agent.auth_state == "active" and agent.session_string:
            managed_groups = await AgentService(self.session).list_managed_member_groups(
                actor_user_id=actor_user_id,
                agent_id=agent.id,
            )
            allowed_group_tg_ids.update(
                canonical_tg_group_id(int(group["tg_group_id"]))
                for group in managed_groups
                if group.get("tg_group_id") is not None
            )
        invalid_group_tg_ids = [group_tg_id for group_tg_id in normalized_group_tg_ids if group_tg_id not in allowed_group_tg_ids]
        if invalid_group_tg_ids:
            raise ValueError("Assigned agent must belong to the selected group")

    def _normalize_group_ids(self, group_ids: Any, *, group_id: int) -> list[int]:
        values = group_ids if isinstance(group_ids, list) else []
        normalized = [int(value) for value in values if value not in {None, ""}]
        return normalized or [int(group_id)]

    def _normalize_group_tg_ids(self, group_tg_ids: Any, *, bound_group: Group | None) -> list[int]:
        values = group_tg_ids if isinstance(group_tg_ids, list) else []
        normalized = [int(value) for value in values if value not in {None, ""}]
        if normalized:
            return normalized
        if bound_group is not None:
            return [int(bound_group.tg_group_id)]
        return []

    def _normalize_group_titles(self, group_titles: Any, *, bound_group: Group | None) -> list[str]:
        values = group_titles if isinstance(group_titles, list) else []
        normalized = [str(value).strip() for value in values if str(value or "").strip()]
        if normalized:
            return normalized
        if bound_group is not None and bound_group.title:
            return [str(bound_group.title)]
        return []

    def _dump_assignment(self, assignment: TaskAssignment, *, group: Group | None = None) -> dict[str, Any]:
        group_id = int(group.id) if group is not None else None
        group_tg_id = int(group.tg_group_id) if group is not None else None
        group_title = str(group.title) if group is not None and group.title is not None else None
        assignment_group_ids = list(assignment.group_ids or ([] if group_id is None else [group_id]))
        assignment_group_tg_ids = list(assignment.group_tg_ids or ([] if group_tg_id is None else [group_tg_id]))
        assignment_group_titles = list(assignment.group_titles or ([] if group_title is None else [group_title]))
        
        payload = TaskAssignmentStore.serialize_assignment(assignment, group_id=group_id)
        payload.update({
            "group_ids": assignment_group_ids,
            "group_tg_ids": assignment_group_tg_ids,
            "group_titles": assignment_group_titles,
            "group_tg_id": assignment_group_tg_ids[0] if assignment_group_tg_ids else group_tg_id,
            "group_title": assignment_group_titles[0] if assignment_group_titles else group_title,
        })
        payload["condition_rules"] = [
            {
                "key": condition.key,
                "operator": condition.operator,
                "value": condition.value,
            }
            for condition in assignment.condition_rules()
        ]
        return payload
