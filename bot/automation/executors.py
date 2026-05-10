from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from typing import Any

import structlog
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from bot.agents.service import AgentService
from bot.core.runtime.automation import (
    AutomationRuntimeService,
    KeywordReplyRequest,
    NotifyDestinationRequest,
)
from bot.automation.models import TaskAssignment, TaskDefinition, TaskEvent
from bot.db.models import Agent, AgentJob

logger = structlog.get_logger(__name__)


def _build_inline_keyboard(buttons: Any) -> InlineKeyboardMarkup | None:
    if not isinstance(buttons, list):
        return None
    rows: list[list[InlineKeyboardButton]] = []
    for item in buttons:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        url = str(item.get("url") or "").strip()
        if not text or not url:
            continue
        rows.append([InlineKeyboardButton(text=text, url=url)])
    if not rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=rows)


class BaseTaskExecutor(ABC):
    @abstractmethod
    async def execute(
        self,
        task: TaskDefinition,
        assignment: TaskAssignment,
        event: TaskEvent,
    ) -> dict[str, Any]:
        raise NotImplementedError


class BotTaskExecutor(BaseTaskExecutor):
    def __init__(
        self,
        dispatch_delete_message: Any | None = None,
        automation_runtime: AutomationRuntimeService | None = None,
    ) -> None:
        self.dispatch_delete_message = dispatch_delete_message
        self.automation_runtime = automation_runtime

    def _schedule_delete(self, *, delay_seconds: int, chat_id: int | str, message_id: int | None) -> None:
        if self.dispatch_delete_message and delay_seconds > 0 and message_id is not None and isinstance(chat_id, int):
            self.dispatch_delete_message(
                delay_seconds=delay_seconds,
                chat_id=chat_id,
                message_id=message_id,
            )

    async def execute(self, task: TaskDefinition, assignment: TaskAssignment, event: TaskEvent) -> dict[str, Any]:
        bot = event.payload.get("bot")
        if bot is None:
            raise ValueError("Bot executor requires bot in event payload")

        result = await task.handler(assignment.config, event)
        if result.get("reply_markup") is None:
            result["reply_markup"] = _build_inline_keyboard(result.get("inline_buttons"))
        if self.automation_runtime is not None and task.key == "reply_message" and result.get("text"):
            return await self.automation_runtime.execute_keyword_reply(
                KeywordReplyRequest(
                    group_id=event.group_id,
                    assignment_id=assignment.assignment_id,
                    task_key=task.key,
                    chat_id=result.get("chat_id", event.payload.get("chat_id", event.group_id)),
                    text=str(result["text"]),
                    reply_to_message_id=result.get("reply_to_message_id"),
                    reply_markup=result.get("reply_markup"),
                    delete_after_seconds=int(result.get("delete_after_seconds") or 0),
                    actor_user_id=event.user_id,
                    source_message_id=event.payload.get("message_id"),
                    metadata={
                        "executor_type": assignment.executor_type,
                        "conditions": dict(assignment.conditions),
                    },
                ),
                bot=bot,
            )
        if self.automation_runtime is not None and task.key == "notify_destination":
            runtime_result = await self.automation_runtime.execute_notify_destination(
                NotifyDestinationRequest(
                    group_id=event.group_id,
                    assignment_id=assignment.assignment_id,
                    task_key=task.key,
                    chat_id=result.get("chat_id", event.payload.get("chat_id", event.group_id)),
                    text=str(result.get("text") or ""),
                    forward_from_chat_id=result.get("forward_from_chat_id"),
                    forward_message_id=result.get("forward_message_id"),
                    copy_from_chat_id=result.get("copy_from_chat_id"),
                    copy_message_id=result.get("copy_message_id"),
                    delete_after_seconds=int(result.get("delete_after_seconds") or 0),
                    actor_user_id=event.user_id,
                    source_message_id=event.payload.get("message_id"),
                    metadata={
                        "executor_type": assignment.executor_type,
                        "conditions": dict(assignment.conditions),
                        **dict(result.get("metadata") or {}),
                    },
                ),
                bot=bot,
            )
            return runtime_result
        chat_id = result.get("chat_id", event.payload.get("chat_id", event.group_id))
        if isinstance(chat_id, str) and chat_id.lstrip("-").isdigit():
            chat_id = int(chat_id)
        delete_after_seconds = int(result.get("delete_after_seconds") or 0)
        metadata = dict(result.get("metadata") or {})
        result["metadata"] = metadata

        if chat_id not in (None, ""):
            metadata["destination_chat_id"] = str(chat_id)

        destination_message_id: int | None = None
        reply_markup = result.get("reply_markup")
        if reply_markup is None:
            reply_markup = _build_inline_keyboard(result.get("inline_buttons"))

        if result.get("text"):
            sent = await bot.send_message(
                chat_id=chat_id,
                text=result["text"],
                reply_to_message_id=result.get("reply_to_message_id"),
                reply_markup=reply_markup,
            )
            destination_message_id = getattr(sent, "message_id", None)
            self._schedule_delete(
                delay_seconds=delete_after_seconds,
                chat_id=chat_id,
                message_id=destination_message_id,
            )

        if result.get("forward_message_id") is not None:
            forwarded = await bot.forward_message(
                chat_id=chat_id,
                from_chat_id=result["forward_from_chat_id"],
                message_id=result["forward_message_id"],
            )
            if destination_message_id is None:
                destination_message_id = getattr(forwarded, "message_id", None)
            self._schedule_delete(
                delay_seconds=delete_after_seconds,
                chat_id=chat_id,
                message_id=getattr(forwarded, "message_id", None),
            )

        if result.get("copy_message_id") is not None:
            copied = await bot.copy_message(
                chat_id=chat_id,
                from_chat_id=result["copy_from_chat_id"],
                message_id=result["copy_message_id"],
            )
            if destination_message_id is None:
                destination_message_id = getattr(copied, "message_id", None)
            self._schedule_delete(
                delay_seconds=delete_after_seconds,
                chat_id=chat_id,
                message_id=getattr(copied, "message_id", None),
            )
        if destination_message_id is not None:
            metadata["destination_message_id"] = str(destination_message_id)
        return result


class AgentJobExecutor(BaseTaskExecutor):
    def __init__(self, agent_service: AgentService, dispatch_job: Any) -> None:
        self.agent_service = agent_service
        self.dispatch_job = dispatch_job

    async def execute(self, task: TaskDefinition, assignment: TaskAssignment, event: TaskEvent) -> dict[str, Any]:
        if assignment.agent_id is None:
            raise ValueError("Agent executor requires agent_id")
        agent = (
            await self.agent_service.session.execute(select(Agent).where(Agent.id == assignment.agent_id))
        ).scalar_one_or_none()
        if agent is None or agent.auth_state != "active":
            logger.warning(
                "agent_task_skipped_unavailable_agent",
                agent_id=assignment.agent_id,
                assignment_id=assignment.assignment_id,
                task_key=task.key,
                event_name=event.name,
                group_id=event.group_id,
                chat_id=event.payload.get("chat_id", event.group_id),
                user_id=event.user_id,
            )
            return {
                "status": "skipped",
                "reason": "assigned_agent_unavailable",
                "agent_id": assignment.agent_id,
            }
        logger.info(
            "agent_message_received_for_task",
            agent_id=agent.id,
            assignment_id=assignment.assignment_id,
            task_key=task.key,
            event_name=event.name,
            group_id=event.group_id,
            chat_id=event.payload.get("chat_id", event.group_id),
            user_id=event.user_id,
            message_id=event.payload.get("message_id"),
            text=str(event.payload.get("text") or ""),
            group_title=str(event.payload.get("group_title") or ""),
            username=str(event.payload.get("username") or ""),
            first_name=str(event.payload.get("first_name") or ""),
            full_name=str(event.payload.get("full_name") or ""),
        )

        job = AgentJob(
            agent_id=agent.id,
            job_type="automation_task",
            job_payload={
                "task_key": task.key,
                "task_config": assignment.config,
                "conditions": assignment.conditions,
                "assignment_id": assignment.assignment_id,
                "event": {
                    "name": event.name,
                    "group_id": event.group_id,
                    "user_id": event.user_id,
                    "payload": {
                        "chat_id": event.payload.get("chat_id", event.group_id),
                        "group_title": event.payload.get("group_title"),
                        "text": event.payload.get("text"),
                        "message_id": event.payload.get("message_id"),
                        "first_name": event.payload.get("first_name"),
                        "full_name": event.payload.get("full_name"),
                        "username": event.payload.get("username"),
                    },
                },
            },
            status="pending",
        )
        self.agent_service.session.add(job)
        await self.agent_service.session.commit()
        dispatch_result = self.dispatch_job(job.id)
        if inspect.isawaitable(dispatch_result):
            await dispatch_result
        return {"job_id": job.id, "status": job.status}
