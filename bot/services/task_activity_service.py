from __future__ import annotations

from typing import Any

from bot.core.runtime.audit import AuditEntry, ModerationLogAuditSink, RuntimeAuditService


class TaskActivityService:
    def __init__(self, session) -> None:
        self.session = session
        self.audit = RuntimeAuditService(ModerationLogAuditSink(session))

    async def log_task_execution(
        self,
        *,
        group_id: int,
        target_user_id: int | None,
        task_key: str,
        assignment_id: str,
        metadata: dict[str, Any] | None = None,
        reason: str | None = None,
    ) -> None:
        details = dict(metadata or {})
        details.update({"task_key": task_key, "assignment_id": assignment_id})
        action = str(details.get("capture_type") or "task_execution")
        action_map = {
            "lead_capture": "lead_captured",
            "welcome_flow": "welcome_flow_sent",
            "escalation_alert": "escalation_alert_sent",
            "notify_destination": "destination_notified",
        }
        await self.audit.record(
            AuditEntry(
                group_id=group_id,
                action=action_map.get(action, action),
                target_user_id=target_user_id,
                actor_user_id=None,
                reason=reason,
                domain="automation",
                event_type="automation.activity_recorded",
                action_type=action,
                subject_type="task_assignment",
                subject_id=assignment_id,
                source_runtime="automation.activity",
                details=details,
            )
        )
        await self.session.commit()

    async def log_follow_up_scheduled(
        self,
        *,
        group_id: int,
        target_user_id: int | None,
        task_key: str,
        assignment_id: str,
        delay_seconds: int,
    ) -> None:
        await self.audit.record(
            AuditEntry(
                group_id=group_id,
                action="task_follow_up_scheduled",
                target_user_id=target_user_id,
                actor_user_id=None,
                domain="automation",
                event_type="automation.activity_recorded",
                action_type="task_follow_up_scheduled",
                subject_type="task_assignment",
                subject_id=assignment_id,
                source_runtime="automation.activity",
                details={
                    "task_key": task_key,
                    "assignment_id": assignment_id,
                    "delay_seconds": delay_seconds,
                },
            )
        )
        await self.session.commit()

    async def log_follow_up_sent(
        self,
        *,
        group_id: int,
        target_user_id: int | None,
        task_key: str,
        assignment_id: str,
        executor_type: str,
    ) -> None:
        await self.audit.record(
            AuditEntry(
                group_id=group_id,
                action="task_follow_up_sent",
                target_user_id=target_user_id,
                actor_user_id=None,
                domain="automation",
                event_type="automation.activity_recorded",
                action_type="task_follow_up_sent",
                subject_type="task_assignment",
                subject_id=assignment_id,
                source_runtime="automation.activity",
                details={
                    "task_key": task_key,
                    "assignment_id": assignment_id,
                    "executor_type": executor_type,
                },
            )
        )
        await self.session.commit()

    async def log_notify_destination_confirmation(
        self,
        *,
        group_id: int,
        target_user_id: int | None,
        task_key: str,
        assignment_id: str,
        token: str,
        status: str,
        confirmed_by_user_id: int | None,
        confirmed_by_username: str | None = None,
        confirmed_by_name: str | None = None,
        destination: str | None = None,
        agent_id: int | None = None,
    ) -> None:
        await self.audit.record(
            AuditEntry(
                group_id=group_id,
                action="notify_destination_confirmation",
                target_user_id=target_user_id,
                actor_user_id=confirmed_by_user_id,
                reason=status,
                domain="automation",
                event_type="automation.activity_recorded",
                action_type="notify_destination_confirmation",
                subject_type="task_assignment",
                subject_id=assignment_id,
                source_runtime="automation.activity",
                details={
                    "task_key": task_key,
                    "assignment_id": assignment_id,
                    "token": token,
                    "status": status,
                    "destination": destination,
                    "agent_id": agent_id,
                    "confirmed_by_username": confirmed_by_username,
                    "confirmed_by_name": confirmed_by_name,
                },
            )
        )
        await self.session.commit()
