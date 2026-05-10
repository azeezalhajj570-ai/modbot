from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.runtime.actions import SendRuntimeMessageAction
from bot.core.runtime.audit import AuditEntry, ModerationLogAuditSink, RuntimeAuditService, serialize_guard_result
from bot.core.runtime.events import RuntimeEvent, RuntimeEventType
from bot.core.runtime.executors import ActionExecutorRegistry
from bot.core.runtime.guards import GuardDecision, GuardPipeline, GuardResult


@dataclass
class KeywordReplyRequest:
    group_id: int
    assignment_id: str
    task_key: str
    chat_id: int | str
    text: str
    reply_to_message_id: int | None = None
    reply_markup: Any | None = None
    delete_after_seconds: int = 0
    actor_user_id: int | None = None
    source_message_id: int | None = None
    source: str = "automation"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScheduledAnnouncementRequest:
    group_id: int
    entry_id: str
    chat_id: int | str
    text: str
    delete_after_seconds: int = 0
    source: str = "automation"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class NotifyDestinationRequest:
    group_id: int
    assignment_id: str
    task_key: str
    chat_id: int | str
    text: str = ""
    forward_from_chat_id: int | str | None = None
    forward_message_id: int | None = None
    copy_from_chat_id: int | str | None = None
    copy_message_id: int | None = None
    delete_after_seconds: int = 0
    actor_user_id: int | None = None
    source_message_id: int | None = None
    source: str = "automation"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskFollowUpRequest:
    group_id: int
    assignment_id: str
    task_key: str
    chat_id: int | str
    text: str
    target_user_id: int | None = None
    delete_after_seconds: int = 0
    source: str = "automation"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class HasMessageOperationGuard:
    async def evaluate(self, event: RuntimeEvent, action: SendRuntimeMessageAction) -> GuardResult:
        _ = event
        has_text = bool(str(action.text or "").strip())
        has_forward = action.forward_from_chat_id is not None and action.forward_message_id is not None
        has_copy = action.copy_from_chat_id is not None and action.copy_message_id is not None
        if not (has_text or has_forward or has_copy):
            return GuardResult(
                decision=GuardDecision.DENY,
                code="empty_message_operation",
                reason="No runtime message operation was provided",
            )
        return GuardResult(decision=GuardDecision.ALLOW)


@dataclass
class ValidDestinationGuard:
    async def evaluate(self, event: RuntimeEvent, action: SendRuntimeMessageAction) -> GuardResult:
        _ = event
        destination = action.chat_id
        if destination in (None, ""):
            return GuardResult(decision=GuardDecision.DENY, code="missing_destination", reason="Destination chat is missing")
        return GuardResult(decision=GuardDecision.ALLOW)


@dataclass
class AutomationRuntimeService:
    session: AsyncSession
    dispatch_delete_message: Any | None = None

    async def execute_keyword_reply(
        self,
        request: KeywordReplyRequest,
        *,
        bot: Bot,
    ) -> dict[str, Any]:
        event = RuntimeEvent(
            name=RuntimeEventType.AUTOMATION_KEYWORD_REPLY_REQUESTED,
            group_id=request.group_id,
            actor_user_id=request.actor_user_id,
            subject_type="task_assignment",
            subject_id=request.assignment_id,
            source=request.source,
            payload={
                "task_key": request.task_key,
                "source_message_id": request.source_message_id,
                **dict(request.metadata),
            },
        )
        action = SendRuntimeMessageAction(
            kind="send_runtime_message",
            group_id=request.group_id,
            chat_id=request.chat_id,
            text=request.text,
            reply_to_message_id=request.reply_to_message_id,
            reply_markup=request.reply_markup,
            delete_after_seconds=max(int(request.delete_after_seconds or 0), 0),
            metadata={
                "task_key": request.task_key,
                "assignment_id": request.assignment_id,
                "source_message_id": request.source_message_id,
                **dict(request.metadata),
            },
        )
        return await self._execute_message_action(
            event,
            action,
            bot=bot,
            audit_action="reply_message_sent",
        )

    async def execute_scheduled_announcement(
        self,
        request: ScheduledAnnouncementRequest,
        *,
        bot: Bot,
    ) -> dict[str, Any]:
        event = RuntimeEvent(
            name=RuntimeEventType.AUTOMATION_SCHEDULED_MESSAGE_DUE,
            group_id=request.group_id,
            actor_user_id=None,
            subject_type="scheduled_message",
            subject_id=request.entry_id,
            source=request.source,
            payload=dict(request.metadata),
        )
        action = SendRuntimeMessageAction(
            kind="send_runtime_message",
            group_id=request.group_id,
            chat_id=request.chat_id,
            text=request.text,
            delete_after_seconds=max(int(request.delete_after_seconds or 0), 0),
            metadata={"entry_id": request.entry_id, **dict(request.metadata)},
        )
        return await self._execute_message_action(
            event,
            action,
            bot=bot,
            audit_action="scheduled_message_sent",
        )

    async def execute_notify_destination(
        self,
        request: NotifyDestinationRequest,
        *,
        bot: Bot,
    ) -> dict[str, Any]:
        event = RuntimeEvent(
            name=RuntimeEventType.AUTOMATION_NOTIFY_DESTINATION_REQUESTED,
            group_id=request.group_id,
            actor_user_id=request.actor_user_id,
            subject_type="task_assignment",
            subject_id=request.assignment_id,
            source=request.source,
            payload={
                "task_key": request.task_key,
                "source_message_id": request.source_message_id,
                **dict(request.metadata),
            },
        )
        action = SendRuntimeMessageAction(
            kind="send_runtime_message",
            group_id=request.group_id,
            chat_id=request.chat_id,
            text=request.text,
            forward_from_chat_id=request.forward_from_chat_id,
            forward_message_id=request.forward_message_id,
            copy_from_chat_id=request.copy_from_chat_id,
            copy_message_id=request.copy_message_id,
            delete_after_seconds=max(int(request.delete_after_seconds or 0), 0),
            metadata={
                "task_key": request.task_key,
                "assignment_id": request.assignment_id,
                "source_message_id": request.source_message_id,
                **dict(request.metadata),
            },
        )
        return await self._execute_message_action(
            event,
            action,
            bot=bot,
            audit_action="destination_notified",
        )

    async def execute_task_follow_up(
        self,
        request: TaskFollowUpRequest,
        *,
        bot: Bot,
    ) -> dict[str, Any]:
        event = RuntimeEvent(
            name=RuntimeEventType.AUTOMATION_TASK_FOLLOW_UP_REQUESTED,
            group_id=request.group_id,
            actor_user_id=None,
            subject_type="task_assignment",
            subject_id=request.assignment_id,
            source=request.source,
            payload={
                "task_key": request.task_key,
                "target_user_id": request.target_user_id,
                **dict(request.metadata),
            },
        )
        action = SendRuntimeMessageAction(
            kind="send_runtime_message",
            group_id=request.group_id,
            chat_id=request.chat_id,
            text=request.text,
            delete_after_seconds=max(int(request.delete_after_seconds or 0), 0),
            metadata={
                "task_key": request.task_key,
                "assignment_id": request.assignment_id,
                "target_user_id": request.target_user_id,
                **dict(request.metadata),
            },
        )
        return await self._execute_message_action(
            event,
            action,
            bot=bot,
            audit_action="task_follow_up_sent",
            target_user_id=request.target_user_id,
        )

    async def _execute_message_action(
        self,
        event: RuntimeEvent,
        action: SendRuntimeMessageAction,
        *,
        bot: Bot,
        audit_action: str,
        target_user_id: int | None = None,
    ) -> dict[str, Any]:
        guard_result = await GuardPipeline(guards=[ValidDestinationGuard(), HasMessageOperationGuard()]).evaluate(event, action)
        if guard_result.decision == GuardDecision.DENY:
            return {"status": "skipped", "reason": guard_result.reason}

        registry = ActionExecutorRegistry()
        registry.register("send_runtime_message", lambda runtime_action: self._send_message(runtime_action, bot=bot))
        result = await registry.execute(action)

        await RuntimeAuditService(ModerationLogAuditSink(self.session)).record(
            AuditEntry(
                action=audit_action,
                action_type=action.kind,
                event_type=event.name,
                group_id=event.group_id,
                actor_user_id=event.actor_user_id,
                target_user_id=target_user_id,
                domain="automation",
                subject_type=event.subject_type,
                subject_id=event.subject_id,
                source_runtime="automation.runtime",
                correlation_id=event.correlation_id,
                details={
                    **dict(action.metadata),
                    "selected_actions": [action.kind],
                    "guard_outcomes": [serialize_guard_result(guard_result)],
                    "execution_result": dict(result),
                    **result,
                },
            )
        )
        await self.session.commit()
        return {"status": "ok", **result}

    async def _send_message(self, action: SendRuntimeMessageAction, *, bot: Bot) -> dict[str, Any]:
        destination_message_id: int | None = None
        forwarded_message_id: int | None = None
        copied_message_id: int | None = None

        if str(action.text or "").strip():
            sent = await bot.send_message(
                chat_id=action.chat_id,
                text=action.text,
                reply_to_message_id=action.reply_to_message_id,
                reply_markup=action.reply_markup,
            )
            destination_message_id = getattr(sent, "message_id", None)
            self._schedule_message_delete(
                chat_id=action.chat_id,
                message_id=destination_message_id,
                delete_after_seconds=action.delete_after_seconds,
            )

        if action.forward_from_chat_id is not None and action.forward_message_id is not None:
            forwarded = await bot.forward_message(
                chat_id=action.chat_id,
                from_chat_id=action.forward_from_chat_id,
                message_id=action.forward_message_id,
            )
            forwarded_message_id = getattr(forwarded, "message_id", None)
            if destination_message_id is None:
                destination_message_id = forwarded_message_id
            self._schedule_message_delete(
                chat_id=action.chat_id,
                message_id=forwarded_message_id,
                delete_after_seconds=action.delete_after_seconds,
            )

        if action.copy_from_chat_id is not None and action.copy_message_id is not None:
            copied = await bot.copy_message(
                chat_id=action.chat_id,
                from_chat_id=action.copy_from_chat_id,
                message_id=action.copy_message_id,
            )
            copied_message_id = getattr(copied, "message_id", None)
            if destination_message_id is None:
                destination_message_id = copied_message_id
            self._schedule_message_delete(
                chat_id=action.chat_id,
                message_id=copied_message_id,
                delete_after_seconds=action.delete_after_seconds,
            )

        result = {
            "chat_id": action.chat_id,
            "destination_message_id": destination_message_id,
            "delete_after_seconds": action.delete_after_seconds,
        }
        if forwarded_message_id is not None:
            result["forwarded_message_id"] = forwarded_message_id
        if copied_message_id is not None:
            result["copied_message_id"] = copied_message_id
        return result

    def _schedule_message_delete(
        self,
        *,
        chat_id: int | str,
        message_id: int | None,
        delete_after_seconds: int,
    ) -> None:
        if (
            self.dispatch_delete_message is not None
            and delete_after_seconds > 0
            and message_id is not None
            and isinstance(chat_id, int)
        ):
            self.dispatch_delete_message(
                delay_seconds=delete_after_seconds,
                chat_id=chat_id,
                message_id=message_id,
            )
