from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

import structlog
from sqlalchemy import select

from bot.agents.exceptions import AgentBannedError, AgentSessionRevokedError
from bot.agents.session import SessionManager
from bot.agents.dispatch import dispatch_agent_job
from bot.config import get_settings
from bot.db.models import Agent, Group, GroupSetting, ModerationLog
from bot.db.session import SessionLocal
from bot.services.group_service import GroupService, canonical_tg_group_id, upsert_group, upsert_group_member
from bot.services.scraper_service import ScraperService
from bot.services.task_assignment_store import TASKS_SETTING_KEY
from bot.services.task_service import TaskService
from bot.workers.tasks import schedule_bot_message_delete, schedule_task_follow_up


logger = structlog.get_logger(__name__)
_URL_RE = re.compile(r"(https?://\S+|www\.\S+)", re.IGNORECASE)


def _message_contains_link(text: str) -> bool:
    return bool(_URL_RE.search(text or ""))


def _is_terminal_listener_error(exc: Exception) -> bool:
    if isinstance(exc, (AgentBannedError, AgentSessionRevokedError)):
        return True
    try:
        from telethon.errors import (
            AuthKeyDuplicatedError,
            AuthKeyNotFound,
            AuthKeyPermEmptyError,
            AuthKeyUnregisteredError,
            PhoneNumberBannedError,
            SessionExpiredError,
            SessionRevokedError,
            UnauthorizedError,
            UserDeactivatedBanError,
            UserDeactivatedError,
        )
    except ImportError:
        return False
    return isinstance(
        exc,
        (
            AuthKeyDuplicatedError,
            AuthKeyNotFound,
            AuthKeyPermEmptyError,
            AuthKeyUnregisteredError,
            PhoneNumberBannedError,
            SessionExpiredError,
            SessionRevokedError,
            UnauthorizedError,
            UserDeactivatedBanError,
            UserDeactivatedError,
        ),
    )


class AgentListenerManager:
    def __init__(
        self,
        *,
        bot: Any,
        session_factory=SessionLocal,
        session_manager: SessionManager | None = None,
        sync_interval_seconds: int = 15,
        log_message_events: bool | None = None,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ) -> None:
        self.bot = bot
        self.session_factory = session_factory
        self.session_manager = session_manager or SessionManager(session_factory=session_factory)
        self.sync_interval_seconds = max(int(sync_interval_seconds), 5)
        if log_message_events is None:
            log_message_events = get_settings().log_agent_listener_messages
        self.log_message_events = bool(log_message_events)
        self.sleep = sleep
        self._agent_tasks: dict[int, asyncio.Task[Any]] = {}
        self._sync_task: asyncio.Task[Any] | None = None
        self._stopping = False

    async def start(self) -> None:
        if self._sync_task is not None and not self._sync_task.done():
            return
        self._stopping = False
        await self._sync_active_agents()
        self._sync_task = asyncio.create_task(self._sync_loop(), name="agent-listener-sync")

    async def stop(self) -> None:
        self._stopping = True
        if self._sync_task is not None:
            self._sync_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._sync_task
            self._sync_task = None
        running_tasks = list(self._agent_tasks.values())
        self._agent_tasks.clear()
        for task in running_tasks:
            task.cancel()
        for task in running_tasks:
            with suppress(asyncio.CancelledError):
                await task

    async def _sync_loop(self) -> None:
        while not self._stopping:
            try:
                await self._sync_active_agents()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("agent_listener_sync_failed")
            await self.sleep(self.sync_interval_seconds)

    async def _sync_active_agents(self) -> None:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(Agent.id).where(
                        Agent.auth_state == "active",
                        Agent.session_string.is_not(None),
                        Agent.status != "banned",
                    )
                )
            ).all()
        active_agent_ids = {int(row.id) for row in rows}
        for agent_id in list(self._agent_tasks):
            if agent_id not in active_agent_ids:
                task = self._agent_tasks.pop(agent_id)
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        for agent_id in active_agent_ids:
            task = self._agent_tasks.get(agent_id)
            if task is None or task.done():
                self._agent_tasks[agent_id] = asyncio.create_task(
                    self._run_agent_listener(agent_id),
                    name=f"agent-listener-{agent_id}",
                )

    async def _run_agent_listener(self, agent_id: int) -> None:
        try:
            from telethon import events
        except ImportError:
            logger.warning("agent_listener_telethon_unavailable", agent_id=agent_id)
            return

        while not self._stopping:
            client = None
            try:
                client = await self.session_manager.get_client(agent_id)

                async def _handle(event) -> None:
                    await self._handle_telethon_message(agent_id, event)

                client.add_event_handler(_handle, events.NewMessage(incoming=True))
                logger.info("agent_listener_started", agent_id=agent_id)

                # Sync groups to DB on start/reload for high-performance search
                async def _sync_groups():
                    with suppress(Exception):
                        async with self.session_factory() as session:
                            await ScraperService(session).sync_agent_groups(agent_id=agent_id, client=client)

                asyncio.create_task(_sync_groups())

                await client.run_until_disconnected()
                logger.warning("agent_listener_disconnected", agent_id=agent_id)
            except asyncio.CancelledError:
                if client is not None:
                    with suppress(Exception):
                        await client.disconnect()
                raise
            except Exception as exc:
                logger.exception("agent_listener_failed", agent_id=agent_id)
                if client is not None:
                    with suppress(Exception):
                        await client.disconnect()
                if _is_terminal_listener_error(exc):
                    if isinstance(exc, AgentSessionRevokedError):
                        await self.session_manager.mark_failed(agent_id)
                    elif isinstance(exc, AgentBannedError):
                        await self.session_manager.mark_banned(agent_id)
                    logger.warning("agent_listener_stopped_terminal_error", agent_id=agent_id, error=type(exc).__name__)
                    return
                if self._stopping:
                    return
                await self.sleep(5)

    async def _handle_telethon_message(self, agent_id: int, event: Any) -> None:
        chat_id = getattr(event, "chat_id", None)
        if chat_id is None:
            return
        chat_id = int(chat_id)
        sender_id = getattr(event, "sender_id", None)
        text = str(getattr(event, "raw_text", None) or "").strip()
        chat = None
        sender = None
        with suppress(Exception):
            chat = await event.get_chat()
        with suppress(Exception):
            sender = await event.get_sender()
        message_id = getattr(event, "message", None) and getattr(event.message, "id", None)
        chat_title = str(getattr(chat, "title", None) or "")
        username = str(getattr(sender, "username", None) or "")
        first_name = str(getattr(sender, "first_name", None) or "")
        full_name = " ".join(
            part for part in [str(getattr(sender, "first_name", None) or "").strip(), str(getattr(sender, "last_name", None) or "").strip()] if part
        )
        if self.log_message_events:
            logger.info(
                "agent_listener_message_seen",
                agent_id=agent_id,
                chat_id=chat_id,
                user_id=int(sender_id) if sender_id is not None else None,
                message_id=message_id,
                text=text,
                group_title=chat_title,
                username=username,
                first_name=first_name,
                full_name=full_name,
                is_group=chat_id < 0,
            )
        if chat_id >= 0:
            return
        await self._persist_seen_group_message(
            agent_id=agent_id,
            chat_id=chat_id,
            group_title=chat_title,
            text=text,
            message_id=message_id,
            user_id=int(sender_id) if sender_id is not None else None,
            first_name=first_name,
            full_name=full_name,
            username=username,
        )
        await self._dispatch_agent_message(
            agent_id,
            chat_id=chat_id,
            group_title=chat_title,
            text=text,
            message_id=message_id,
            user_id=int(sender_id) if sender_id is not None else None,
            first_name=first_name,
            full_name=full_name,
            username=username,
        )

    async def _persist_seen_group_message(
        self,
        *,
        agent_id: int,
        chat_id: int,
        group_title: str,
        text: str,
        message_id: int | None,
        user_id: int | None,
        first_name: str = "",
        full_name: str = "",
        username: str = "",
    ) -> None:
        try:
            async with self.session_factory() as session:
                agent = (await session.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
                owner_user_id = int(agent.linked_by_user_id) if agent is not None and agent.linked_by_user_id is not None else None
                group = await GroupService(session).get_or_create_by_tg_id(
                    tg_group_id=chat_id,
                    title=group_title or None,
                    owner_tg_user_id=owner_user_id,
                    is_active=False,
                )
                if user_id is not None:
                    await upsert_group_member(
                        session,
                        group_id=group.id,
                        tg_user_id=int(user_id),
                        username=username or None,
                        full_name=full_name or first_name or None,
                        role="member",
                        source="agent_message_seen",
                    )
                session.add(
                    ModerationLog(
                        group_id=group.id,
                        action="agent_message_seen",
                        target_user_id=user_id,
                        admin_user_id=int(agent.telegram_user_id) if agent is not None and agent.telegram_user_id is not None else None,
                        reason=text or None,
                        details={
                            "agent_id": agent_id,
                            "chat_id": int(chat_id),
                            "group_title": group_title,
                            "message_id": int(message_id) if message_id is not None else None,
                            "text": text,
                            "username": username,
                            "first_name": first_name,
                            "full_name": full_name,
                        },
                    )
                )
                await session.commit()
        except Exception:
            logger.exception("agent_listener_message_persist_failed", agent_id=agent_id, chat_id=chat_id)

    async def _dispatch_agent_message(
        self,
        agent_id: int,
        *,
        chat_id: int,
        group_title: str,
        text: str,
        message_id: int | None,
        user_id: int | None,
        first_name: str = "",
        full_name: str = "",
        username: str = "",
    ) -> bool:
        async with self.session_factory() as session:
            group = await self._resolve_listener_group(session, agent_id=agent_id, chat_id=chat_id)
            if group is None:
                return False
            if self.log_message_events:
                logger.info(
                    "agent_listener_message_received",
                    agent_id=agent_id,
                    group_id=group.id,
                    chat_id=chat_id,
                    user_id=user_id,
                    message_id=message_id,
                    text=text,
                )
            await TaskService(
                session,
                dispatch_agent_job=dispatch_agent_job,
                dispatch_follow_up=schedule_task_follow_up,
                dispatch_delete_message=schedule_bot_message_delete,
            ).handle_agent_message_event(
                group_id=group.id,
                agent_id=agent_id,
                source_chat_id=chat_id,
                user_id=user_id,
                payload={
                    "chat_id": chat_id,
                    "group_title": group.title or group_title,
                    "text": text,
                    "message_id": message_id,
                    "first_name": first_name,
                    "full_name": full_name,
                    "username": username,
                    "bot": self.bot,
                    "contains_link": _message_contains_link(text),
                    "lang": get_settings().default_language,
                },
            )
            return True

    async def _resolve_listener_group(self, session: Any, *, agent_id: int, chat_id: int) -> Group | None:
        rows = (
            await session.execute(
                select(Group.id, Group.tg_group_id, Group.title, GroupSetting.value)
                .join(GroupSetting, GroupSetting.group_id == Group.id)
                .where(GroupSetting.key == TASKS_SETTING_KEY)
            )
        ).all()
        canonical_chat_id = canonical_tg_group_id(int(chat_id))
        for row in rows:
            assignments = row.value.get("value") if isinstance(row.value, dict) else None
            if not isinstance(assignments, list):
                continue
            has_matching_assignment = any(
                isinstance(item, dict)
                and str(item.get("executor_type") or "").strip() == "agent"
                and int(item.get("agent_id") or 0) == agent_id
                and bool(item.get("enabled", True))
                and (
                    any(
                        canonical_tg_group_id(int(group_tg_id)) == canonical_chat_id
                        for group_tg_id in (item.get("group_tg_ids") or [])
                        if group_tg_id not in {None, ""}
                    )
                    or (
                        not (item.get("group_tg_ids") or [])
                        and canonical_tg_group_id(int(row.tg_group_id)) == canonical_chat_id
                    )
                )
                for item in assignments
            )
            if not has_matching_assignment:
                continue
            group_rows = (
                await session.execute(select(Group).where(Group.id == int(row.id)))
            ).scalars().all()
            if group_rows:
                return group_rows[0]
        return None
