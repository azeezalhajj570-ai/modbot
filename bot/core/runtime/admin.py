from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import select

from bot.core.runtime.automation import ScheduledAnnouncementRequest
from bot.db.models import Group
from bot.services.scheduled_message_service import ScheduledMessageService
from bot.services.task_service import TaskService


logger = structlog.get_logger(__name__)


def schedule_delay_seconds(send_at: str) -> int:
    return max(0, int((datetime.fromisoformat(send_at) - datetime.utcnow()).total_seconds()))


@dataclass
class AdminAutomationRuntimeService:
    session: Any
    dispatch_agent_job: Any
    dispatch_follow_up: Any | None = None
    dispatch_delete_message: Any | None = None
    schedule_announcement: Any | None = None
    bot: Any | None = None

    async def broadcast_admin_action(
        self,
        *,
        group_id: int,
        actor_user_id: int,
        action: str,
        title: str,
        body: str,
        payload: dict[str, Any] | None = None,
        skip_telegram: bool = False,
    ) -> None:
        """Records a notification and optionally sends it to the admin via Telegram."""
        from bot.agents.agent_notification_service import AgentNotificationService
        from bot.utils.i18n import t
        from bot.services.user_service import UserService

        # 1. Record database notification
        service = AgentNotificationService(self.session)
        try:
            await service.create_notification(
                actor_user_id=actor_user_id,
                group_id=group_id,
                kind=action,
                title=title,
                body=body,
                payload=payload,
            )
        except Exception as exc:
            await self.session.rollback()
            logger.warning(
                "admin_notification_persist_failed",
                group_id=group_id,
                actor_user_id=actor_user_id,
                action=action,
                error=str(exc),
            )

        # 2. Send Telegram notification to the actor (admin)
        if not skip_telegram and self.bot is not None:
            user_service = UserService(self.session)
            lang = await user_service.resolve_language(actor_user_id)
            
            group = (await self.session.execute(select(Group).where(Group.id == group_id))).scalar_one_or_none()
            group_title = group.title if group else f"Group {group_id}"
            
            message = f"🔔 *{title}*\n\n{body}\n\n📍 Group: {group_title}"
            try:
                await self.bot.send_message(
                    chat_id=actor_user_id,
                    text=message,
                    parse_mode="Markdown",
                )
            except Exception:
                # Best effort for Telegram notifications
                pass

    def _task_service(self) -> TaskService:
        return TaskService(
            self.session,
            dispatch_agent_job=self.dispatch_agent_job,
            dispatch_follow_up=self.dispatch_follow_up,
            dispatch_delete_message=self.dispatch_delete_message,
        )

    async def list_task_catalog(self) -> list[dict[str, Any]]:
        return await self._task_service().list_catalog()

    async def list_assignments(self, *, actor_user_id: int, group_id: int) -> list[dict[str, Any]]:
        return await self._task_service().list_assignments(actor_user_id=actor_user_id, group_id=group_id)

    async def save_assignment(
        self,
        *,
        actor_user_id: int,
        group_id: int,
        assignment_id: str | None,
        task_key: str,
        executor_type: str,
        enabled: bool,
        conditions: dict[str, Any],
        config: dict[str, Any],
        agent_id: int | None,
        group_ids: list[int] | None = None,
        group_tg_ids: list[int] | None = None,
        group_titles: list[str] | None = None,
    ) -> dict[str, Any]:
        result = await self._task_service().save_assignment(
            actor_user_id=actor_user_id,
            group_id=group_id,
            assignment_id=assignment_id,
            task_key=task_key,
            executor_type=executor_type,
            enabled=enabled,
            conditions=conditions,
            config=config,
            agent_id=agent_id,
            group_ids=group_ids,
            group_tg_ids=group_tg_ids,
            group_titles=group_titles,
        )
        action_title = "Task Updated" if assignment_id else "Task Created"
        task_title = task_key.replace("_", " ").title()
        await self.broadcast_admin_action(
            group_id=group_id,
            actor_user_id=actor_user_id,
            action="task_saved",
            title=action_title,
            body=f"Automation task '{task_title}' has been saved.",
            payload={"task_key": task_key, "assignment_id": result.get("assignment_id")},
            skip_telegram=agent_id is not None,
        )
        return result

    async def delete_assignment(self, *, actor_user_id: int, group_id: int, assignment_id: str) -> bool:
        assignments_before = await self._task_service().store.list_assignments(group_id)
        was_agent_task = any(
            a.assignment_id == assignment_id and a.executor_type == "agent"
            for a in assignments_before
        )
        deleted = await self._task_service().delete_assignment(
            actor_user_id=actor_user_id,
            group_id=group_id,
            assignment_id=assignment_id,
        )
        if deleted:
            await self.broadcast_admin_action(
                group_id=group_id,
                actor_user_id=actor_user_id,
                action="task_deleted",
                title="Task Deleted",
                body="An automation task has been removed from this group.",
                payload={"assignment_id": assignment_id},
                skip_telegram=was_agent_task,
            )
        return deleted

    async def list_scheduled_messages(self, *, group_id: int) -> list[dict[str, Any]]:
        return await ScheduledMessageService(self.session).list_entries(group_id=group_id)

    async def create_scheduled_message(
        self,
        *,
        actor_user_id: int,
        group_id: int,
        text: str,
        schedule: str,
        delete_after_seconds: int | None,
    ) -> dict[str, Any]:
        entry = await ScheduledMessageService(self.session).save_entry(
            group_id=group_id,
            text=text,
            schedule=schedule,
            delete_after_seconds=delete_after_seconds,
        )
        if self.schedule_announcement is not None:
            self.schedule_announcement(
                delay_seconds=schedule_delay_seconds(entry["send_at"]),
                group_id=group_id,
                entry_id=entry["id"],
                expected_send_at=entry["send_at"],
            )
        
        await self.broadcast_admin_action(
            group_id=group_id,
            actor_user_id=actor_user_id,
            action="message_scheduled",
            title="Message Scheduled",
            body=f"A new message has been scheduled for {entry.get('send_at')}.",
            payload={"entry_id": entry["id"], "schedule": schedule},
        )
        return entry

    async def update_scheduled_message(
        self,
        *,
        actor_user_id: int,
        group_id: int,
        entry_id: str,
        text: str,
        schedule: str,
        delete_after_seconds: int | None,
    ) -> dict[str, Any]:
        entry = await ScheduledMessageService(self.session).save_entry(
            group_id=group_id,
            text=text,
            schedule=schedule,
            entry_id=entry_id,
            delete_after_seconds=delete_after_seconds,
        )
        if self.schedule_announcement is not None:
            self.schedule_announcement(
                delay_seconds=schedule_delay_seconds(entry["send_at"]),
                group_id=group_id,
                entry_id=entry["id"],
                expected_send_at=entry["send_at"],
            )
        
        await self.broadcast_admin_action(
            group_id=group_id,
            actor_user_id=actor_user_id,
            action="message_updated",
            title="Scheduled Message Updated",
            body=f"Scheduled message details have been updated. Next run: {entry.get('send_at')}.",
            payload={"entry_id": entry_id, "schedule": schedule},
        )
        return entry

    async def delete_scheduled_message(self, *, actor_user_id: int, group_id: int, entry_id: str) -> bool:
        deleted = await ScheduledMessageService(self.session).delete_entry(group_id=group_id, entry_id=entry_id)
        if deleted:
            await self.broadcast_admin_action(
                group_id=group_id,
                actor_user_id=actor_user_id,
                action="message_deleted",
                title="Scheduled Message Deleted",
                body="A scheduled message has been removed.",
                payload={"entry_id": entry_id},
            )
        return deleted

    async def get_scheduled_message_dispatch_request(
        self,
        *,
        group_id: int,
        entry_id: str,
    ) -> ScheduledAnnouncementRequest | None:
        entry = await ScheduledMessageService(self.session).get_entry(group_id=group_id, entry_id=entry_id)
        if entry is None or entry.get("status") == "sent":
            return None

        group = (await self.session.execute(select(Group).where(Group.id == group_id))).scalar_one_or_none()
        if group is None:
            return None

        return self.build_scheduled_announcement_request(
            group_id=group_id,
            entry_id=entry_id,
            chat_id=group.tg_group_id,
            text=str(entry.get("text") or ""),
            delete_after_seconds=int(entry.get("delete_after_seconds") or 0),
            metadata={"cron": entry.get("cron")},
        )

    async def send_scheduled_message_now(
        self,
        *,
        group_id: int,
        entry_id: str,
        bot: Any,
    ) -> dict[str, Any]:
        from bot.core.runtime.automation import AutomationRuntimeService
        request = await self.get_scheduled_message_dispatch_request(group_id=group_id, entry_id=entry_id)
        if request is None:
            return {"status": "skipped", "reason": "entry_not_found_or_already_sent"}

        result = await AutomationRuntimeService(
            self.session,
            dispatch_delete_message=self.dispatch_delete_message,
        ).execute_scheduled_announcement(request, bot=bot)

        now = datetime.utcnow()
        updated = await self.mark_scheduled_message_delivered(
            group_id=group_id,
            entry_id=entry_id,
            delivered_at=now,
        )
        if updated and updated.get("cron"):
            next_send_at = updated.get("send_at")
            if isinstance(next_send_at, str) and self.schedule_announcement is not None:
                next_send_at_dt = datetime.fromisoformat(next_send_at)
                self.schedule_announcement(
                    delay_seconds=max(1, int((next_send_at_dt - now).total_seconds())),
                    group_id=group_id,
                    entry_id=entry_id,
                )

        return {"status": "ok", "result": result}

    async def mark_scheduled_message_delivered(
        self,
        *,
        group_id: int,
        entry_id: str,
        delivered_at: datetime | None = None,
    ) -> dict[str, Any] | None:
        return await ScheduledMessageService(self.session).mark_delivered(
            group_id=group_id,
            entry_id=entry_id,
            delivered_at=delivered_at,
        )

    def build_scheduled_announcement_request(
        self,
        *,
        group_id: int,
        entry_id: str,
        chat_id: int | str,
        text: str,
        delete_after_seconds: int | None,
        metadata: dict[str, Any] | None = None,
    ) -> ScheduledAnnouncementRequest:
        return ScheduledAnnouncementRequest(
            group_id=group_id,
            entry_id=entry_id,
            chat_id=chat_id,
            text=text,
            delete_after_seconds=max(int(delete_after_seconds or 0), 0),
            metadata=dict(metadata or {}),
        )
