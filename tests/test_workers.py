from __future__ import annotations

from datetime import datetime
import os
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from aiogram.types import MessageEntity
from redis import Redis
from sqlalchemy import select

from bot.core.event_bus import EventBus
from bot.db.models import Agent, AgentJob, Group, GroupAdminRole, ModerationLog, Warning
from bot.handlers.moderation.events import on_group_message, on_new_chat_members
from bot.services.moderation_notice_service import build_rule_notice
from bot.services.settings_service import SettingsService
from bot.workers import tasks


def test_run_spam_analysis_executes_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    run_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(tasks, "_run_spam_analysis", run_mock)

    result = tasks.run_spam_analysis.fn(-10010, 10, 77, "suspicious http://example", "en")

    assert result is None
    run_mock.assert_awaited_once_with(-10010, 10, 77, "suspicious http://example", "en")


def test_other_workers_execute_without_error() -> None:
    assert tasks.aggregate_group_analytics.fn(123) is None
    assert tasks.cleanup_expired_messages.fn(123) is None


def test_membership_worker_is_registered() -> None:
    assert tasks.run_membership_add_job is tasks.add_user_to_group_task


@pytest.mark.asyncio
async def test_membership_worker_skips_aborted_job(
    patch_db_dependencies,
    db_session,
    session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    add_user_mock = AsyncMock()
    monkeypatch.setattr(tasks, "add_user_to_group", add_user_mock)

    group = Group(tg_group_id=-1008881, title="Skip Aborted Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    agent = Agent(
        group_id=group.id,
        telegram_user_id=99981,
        linked_by_user_id=99981,
        external_account_id="skip-aborted",
        auth_state="active",
        session_string="session",
    )
    db_session.add(agent)
    await db_session.flush()
    job = AgentJob(
        agent_id=agent.id,
        job_type="member_add",
        status="aborted",
        job_payload={
            "user_id": 555001,
            "requested_by": 99981,
            "target_group_id": group.id,
            "target_tg_group_id": group.tg_group_id,
        },
    )
    db_session.add(job)
    await db_session.commit()

    await tasks._run_add_user_to_group_task_with_agent(
        group.id,
        555001,
        99981,
        agent.id,
        group.tg_group_id,
        job.id,
    )

    await db_session.refresh(job)
    assert job.status == "aborted"
    add_user_mock.assert_not_called()


@pytest.mark.asyncio
async def test_run_spam_analysis_warns_user_and_persists_warning(
    patch_db_dependencies,
    seeded_group,
    db_session,
    session_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(tasks, "Bot", lambda token: fake_bot)
    monkeypatch.setattr(
        tasks,
        "pipeline",
        SimpleNamespace(
            process=AsyncMock(
                return_value=SimpleNamespace(
                    decision=tasks.ModerationDecision.WARN,
                    reason="promotional_content",
                    score=0.7,
                )
            )
        ),
    )

    target_user_id = 2001

    await tasks._run_spam_analysis(
        seeded_group["tg_group_id"],
        600,
        target_user_id,
        "promo offer",
        "en",
    )

    warnings = (
        await db_session.execute(
            select(Warning).where(
                Warning.group_id == seeded_group["group_id"],
                Warning.user_id == target_user_id,
            )
        )
    ).scalars().all()
    assert len(warnings) == 1
    assert warnings[0].count == 1
    assert fake_bot.sent_messages == [
        (seeded_group["tg_group_id"], build_rule_notice("en", "anti_spam_warn", count=1, limit=3))
    ]


@pytest.mark.asyncio
async def test_run_spam_analysis_can_mute_spam_sender(
    patch_db_dependencies,
    seeded_group,
    db_session,
    session_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await SettingsService(db_session).set_value(seeded_group["group_id"], "anti_spam_mute", True)
    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(tasks, "Bot", lambda token: fake_bot)
    monkeypatch.setattr(
        tasks,
        "pipeline",
        SimpleNamespace(
            process=AsyncMock(
                return_value=SimpleNamespace(
                    decision=tasks.ModerationDecision.WARN,
                    reason="promotional_content",
                    score=0.7,
                )
            )
        ),
    )

    target_user_id = 2002

    await tasks._run_spam_analysis(
        seeded_group["tg_group_id"],
        602,
        target_user_id,
        "promo offer",
        "en",
    )

    assert fake_bot.muted_members == [(seeded_group["tg_group_id"], target_user_id)]
    logs = (
        await db_session.execute(
            select(ModerationLog).where(ModerationLog.group_id == seeded_group["group_id"])
        )
    ).scalars().all()
    assert any(log.action == "mute_spam_user" for log in logs)


@pytest.mark.asyncio
async def test_run_spam_analysis_respects_spam_mute_threshold(
    patch_db_dependencies,
    seeded_group,
    db_session,
    session_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await SettingsService(db_session).set_value(seeded_group["group_id"], "anti_spam_mute", True)
    await SettingsService(db_session).set_value(seeded_group["group_id"], "anti_spam_mute_limit", 2)
    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(tasks, "Bot", lambda token: fake_bot)
    monkeypatch.setattr(
        tasks,
        "pipeline",
        SimpleNamespace(
            process=AsyncMock(
                return_value=SimpleNamespace(
                    decision=tasks.ModerationDecision.WARN,
                    reason="promotional_content",
                    score=0.7,
                )
            )
        ),
    )

    target_user_id = 2003

    await tasks._run_spam_analysis(
        seeded_group["tg_group_id"],
        604,
        target_user_id,
        "promo offer",
        "en",
    )

    assert fake_bot.muted_members == []

    await tasks._run_spam_analysis(
        seeded_group["tg_group_id"],
        605,
        target_user_id,
        "promo offer again",
        "en",
    )

    assert fake_bot.muted_members == [(seeded_group["tg_group_id"], target_user_id)]


@pytest.mark.asyncio
async def test_run_spam_analysis_warn_branch_delegates_to_runtime_facade(
    patch_db_dependencies,
    seeded_group,
    session_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_calls: list[dict[str, object]] = []

    async def fake_warning(self, request, *, bot) -> dict[str, object]:
        runtime_calls.append({"request": request, "bot": bot})
        return {"status": "ok", "action": "warn_spam"}

    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(tasks, "Bot", lambda token: fake_bot)
    monkeypatch.setattr(tasks.ModerationRuntimeService, "enforce_flagged_warning", fake_warning)
    monkeypatch.setattr(
        tasks,
        "pipeline",
        SimpleNamespace(
            process=AsyncMock(
                return_value=SimpleNamespace(
                    decision=tasks.ModerationDecision.WARN,
                    reason="promotional_content",
                    score=0.7,
                )
            )
        ),
    )

    await tasks._run_spam_analysis(
        seeded_group["tg_group_id"],
        606,
        2010,
        "promo offer",
        "en",
    )

    assert len(runtime_calls) == 1
    request = runtime_calls[0]["request"]
    assert request.group_id == seeded_group["group_id"]
    assert request.chat_id == seeded_group["tg_group_id"]
    assert request.log_action == "warn_spam"
    assert runtime_calls[0]["bot"] is fake_bot


@pytest.mark.asyncio
async def test_run_spam_analysis_deletes_message_and_notifies_user(
    patch_db_dependencies,
    seeded_group,
    db_session,
    session_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(tasks, "Bot", lambda token: fake_bot)
    monkeypatch.setattr(
        tasks,
        "pipeline",
        SimpleNamespace(
            process=AsyncMock(
                return_value=SimpleNamespace(
                    decision=tasks.ModerationDecision.DELETE,
                    reason="promotional_spam",
                    score=0.9,
                )
            )
        ),
    )

    target_user_id = 2004

    await tasks._run_spam_analysis(
        seeded_group["tg_group_id"],
        601,
        target_user_id,
        "guaranteed profit",
        "en",
    )

    assert fake_bot.deleted_messages == [(seeded_group["tg_group_id"], 601)]
    assert fake_bot.sent_messages == [
        (seeded_group["tg_group_id"], build_rule_notice("en", "anti_spam_delete"))
    ]
    logs = (
        await db_session.execute(
            select(ModerationLog).where(ModerationLog.group_id == seeded_group["group_id"])
        )
    ).scalars().all()
    assert any(log.action == "delete_spam" and log.details.get("message_id") == 601 for log in logs)


@pytest.mark.asyncio
async def test_run_spam_analysis_delete_branch_delegates_to_runtime_facade(
    patch_db_dependencies,
    seeded_group,
    session_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_calls: list[dict[str, object]] = []

    async def fake_enforce(self, request, *, bot) -> dict[str, object]:
        runtime_calls.append({"request": request, "bot": bot})
        return {"status": "ok", "action": "delete_spam"}

    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(tasks, "Bot", lambda token: fake_bot)
    monkeypatch.setattr(tasks.ModerationRuntimeService, "enforce_flagged_message", fake_enforce)
    monkeypatch.setattr(
        tasks,
        "pipeline",
        SimpleNamespace(
            process=AsyncMock(
                return_value=SimpleNamespace(
                    decision=tasks.ModerationDecision.DELETE,
                    reason="promotional_spam",
                    score=0.9,
                )
            )
        ),
    )

    await tasks._run_spam_analysis(
        seeded_group["tg_group_id"],
        611,
        2011,
        "guaranteed profit",
        "en",
    )

    assert runtime_calls
    assert runtime_calls[0]["request"].delete_log_action == "delete_spam"
    assert runtime_calls[0]["request"].source == "anti_spam"


@pytest.mark.asyncio
async def test_run_spam_analysis_removes_user_on_warning_limit(
    patch_db_dependencies,
    seeded_group,
    db_session,
    session_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await SettingsService(db_session).set_value(seeded_group["group_id"], "warn_auto_remove", True)
    await SettingsService(db_session).set_value(seeded_group["group_id"], "warn_remove_limit", 2)
    target_user_id = 2005
    db_session.add(Warning(group_id=seeded_group["group_id"], user_id=target_user_id, issued_by=None, reason="spam", count=1))
    await db_session.commit()

    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(tasks, "Bot", lambda token: fake_bot)
    monkeypatch.setattr(
        tasks,
        "pipeline",
        SimpleNamespace(
            process=AsyncMock(
                return_value=SimpleNamespace(
                    decision=tasks.ModerationDecision.WARN,
                    reason="promotional_content",
                    score=0.7,
                )
            )
        ),
    )

    await tasks._run_spam_analysis(
        seeded_group["tg_group_id"],
        603,
        target_user_id,
        "promo offer",
        "en",
    )

    assert fake_bot.banned_members == [(seeded_group["tg_group_id"], target_user_id)]
    assert fake_bot.sent_messages == [
        (seeded_group["tg_group_id"], build_rule_notice("en", "warn_limit_remove", count=2, limit=2))
    ]
    logs = (
        await db_session.execute(
            select(ModerationLog).where(ModerationLog.group_id == seeded_group["group_id"])
        )
    ).scalars().all()
    assert any(log.action == "remove_warn_limit" for log in logs)


@pytest.mark.asyncio
async def test_run_spam_analysis_skips_group_admins(
    patch_db_dependencies,
    seeded_group,
    db_session,
    session_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_session.add(GroupAdminRole(group_id=seeded_group["group_id"], user_id=2006, role="moderator"))
    await db_session.commit()

    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(tasks, "Bot", lambda token: fake_bot)
    monkeypatch.setattr(
        tasks,
        "pipeline",
        SimpleNamespace(
            process=AsyncMock(
                return_value=SimpleNamespace(
                    decision=tasks.ModerationDecision.WARN,
                    reason="promotional_content",
                    score=0.7,
                )
            )
        ),
    )

    await tasks._run_spam_analysis(
        seeded_group["tg_group_id"],
        606,
        2006,
        "promo offer",
        "en",
    )

    warnings = (
        await db_session.execute(
            select(Warning).where(
                Warning.group_id == seeded_group["group_id"],
                Warning.user_id == 2006,
            )
        )
    ).scalars().all()
    logs = (
        await db_session.execute(
            select(ModerationLog).where(
                ModerationLog.group_id == seeded_group["group_id"],
                ModerationLog.target_user_id == 2006,
            )
        )
    ).scalars().all()

    assert warnings == []
    assert logs == []
    assert fake_bot.sent_messages == []
    assert fake_bot.deleted_messages == []
    assert fake_bot.muted_members == []


@pytest.mark.asyncio
async def test_on_group_message_logs_moderation_entry(
    patch_db_dependencies,
    patch_moderation_events_session,
    seeded_group,
    fake_message_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_events: list[tuple[str, dict[str, Any]]] = []

    monkeypatch.setattr("bot.handlers.moderation.events.run_spam_analysis.send", Mock())

    from bot.handlers.moderation import events as moderation_events

    monkeypatch.setattr(
        moderation_events.logger,
        "info",
        lambda event_name, **kwargs: log_events.append((event_name, kwargs)),
    )

    message = fake_message_factory(
        chat_id=seeded_group["tg_group_id"],
        chat_type="group",
        user_id=seeded_group["user_id"],
        text="normal message",
        message_id=504,
        bot=fake_bot,
    )

    await on_group_message(message, EventBus())

    assert ("moderation_group_message_received", {
        "chat_id": seeded_group["tg_group_id"],
        "chat_type": "group",
        "user_id": seeded_group["user_id"],
        "message_id": 504,
        "has_text": True,
    }) in log_events
    assert ("moderation_message_trace", {
        "chat_id": seeded_group["tg_group_id"],
        "chat_type": "group",
        "user_id": seeded_group["user_id"],
        "message_id": 504,
        "text": "normal message",
        "has_text": True,
        "contains_link": False,
        "entity_types": [],
        "caption_entity_types": [],
    }) in log_events
    assert ("moderation_message_publish", {
        "chat_id": seeded_group["tg_group_id"],
        "chat_type": "group",
        "user_id": seeded_group["user_id"],
        "message_id": 504,
        "contains_link": False,
        "text": "normal message",
    }) in log_events


@pytest.mark.asyncio
async def test_on_group_message_ignores_bot_commands(
    patch_db_dependencies,
    patch_moderation_events_session,
    seeded_group,
    fake_message_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_events: list[tuple[str, dict[str, Any]]] = []

    monkeypatch.setattr("bot.handlers.moderation.events.run_spam_analysis.send", Mock())

    from bot.handlers.moderation import events as moderation_events

    monkeypatch.setattr(
        moderation_events.logger,
        "info",
        lambda event_name, **kwargs: log_events.append((event_name, kwargs)),
    )

    message = fake_message_factory(
        chat_id=seeded_group["tg_group_id"],
        chat_type="group",
        user_id=seeded_group["user_id"],
        text="/ban",
        message_id=505,
        bot=fake_bot,
        entities=[MessageEntity(type="bot_command", offset=0, length=4)],
    )

    await on_group_message(message, EventBus())

    assert log_events == []


@pytest.mark.asyncio
async def test_on_new_chat_members_triggers_welcome_flow(
    patch_db_dependencies,
    patch_moderation_events_session,
    seeded_group,
    db_session,
    fake_message_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bot.services.task_service import TaskService

    service = TaskService(db_session, dispatch_agent_job=lambda _: None, dispatch_follow_up=None)
    await service.save_assignment(
        actor_user_id=seeded_group["user_id"],
        group_id=seeded_group["group_id"],
        task_key="welcome_flow",
        executor_type="bot",
        config={"message_template": "Welcome {first_name}!"},
    )

    monkeypatch.setattr("bot.handlers.moderation.events.schedule_task_follow_up", lambda **_: None)
    monkeypatch.setattr("bot.handlers.moderation.events.execute_agent_job.send", Mock())

    new_member = SimpleNamespace(id=2222, first_name="Sara", full_name="Sara Smith", is_bot=False)
    message = fake_message_factory(
        chat_id=seeded_group["tg_group_id"],
        chat_type="group",
        user_id=seeded_group["user_id"],
        text="",
        message_id=700,
        bot=fake_bot,
        new_chat_members=[new_member],
    )

    await on_new_chat_members(message)

    assert fake_bot.sent_messages == [(seeded_group["tg_group_id"], "Welcome Sara!")]


@pytest.mark.asyncio
async def test_run_task_follow_up_sends_message_and_logs(
    patch_db_dependencies,
    seeded_group,
    db_session,
    session_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(tasks, "Bot", lambda token: fake_bot)

    await tasks._run_task_follow_up(
        seeded_group["group_id"],
        seeded_group["tg_group_id"],
        "bot",
        None,
        "Follow up",
        "assignment-1",
        "welcome_flow",
        seeded_group["user_id"],
    )

    logs = (
        await db_session.execute(select(ModerationLog).where(ModerationLog.group_id == seeded_group["group_id"]))
    ).scalars().all()
    assert fake_bot.sent_messages == [(seeded_group["tg_group_id"], "Follow up")]
    assert any(log.action == "task_follow_up_sent" for log in logs)


@pytest.mark.asyncio
async def test_run_task_follow_up_can_schedule_message_deletion(
    patch_db_dependencies,
    seeded_group,
    session_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delete_calls: list[tuple[int, int, int]] = []
    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(tasks, "Bot", lambda token: fake_bot)
    monkeypatch.setattr(
        tasks,
        "schedule_bot_message_delete",
        lambda *, delay_seconds, chat_id, message_id: delete_calls.append((delay_seconds, chat_id, message_id)),
    )

    await tasks._run_task_follow_up(
        seeded_group["group_id"],
        seeded_group["tg_group_id"],
        "bot",
        None,
        "Delete me soon",
        "assignment-2",
        "welcome_flow",
        seeded_group["user_id"],
        45,
    )

    assert delete_calls == [(45, seeded_group["tg_group_id"], 1001)]


@pytest.mark.asyncio
async def test_run_task_follow_up_delegates_bot_delivery_to_runtime_service(
    patch_db_dependencies,
    seeded_group,
    session_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_calls: list[dict[str, object]] = []

    async def fake_execute(self, request, *, bot) -> dict[str, object]:
        runtime_calls.append({"request": request, "bot": bot})
        return {"status": "ok", "destination_message_id": 1001}

    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(tasks, "Bot", lambda token: fake_bot)
    monkeypatch.setattr("bot.workers.tasks.AutomationRuntimeService.execute_task_follow_up", fake_execute)

    await tasks._run_task_follow_up(
        seeded_group["group_id"],
        seeded_group["tg_group_id"],
        "bot",
        None,
        "Runtime follow up",
        "assignment-runtime",
        "welcome_flow",
        seeded_group["user_id"],
        45,
    )

    assert runtime_calls[0]["request"].assignment_id == "assignment-runtime"
    assert runtime_calls[0]["request"].task_key == "welcome_flow"
    assert runtime_calls[0]["request"].delete_after_seconds == 45
    assert runtime_calls[0]["bot"] is fake_bot


@pytest.mark.asyncio
async def test_run_scheduled_announcement_sends_message_and_reschedules_cron(
    patch_db_dependencies,
    seeded_group,
    session_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FrozenDateTime(datetime):
        @classmethod
        def utcnow(cls) -> datetime:
            return cls(2026, 3, 13, 11, 46, 30)

    async with session_factory() as session:
        await SettingsService(session).set_value(
            seeded_group["group_id"],
            "announcement_schedules",
            [
                {
                    "id": "announcement-1",
                    "text": "Recurring reminder",
                    "send_at": "2026-03-13T11:45",
                    "status": "pending",
                    "cron": "*/15 * * * *",
                    "delete_after_seconds": 30,
                }
            ],
        )

    reschedules: list[tuple[int, int, str]] = []
    delete_calls: list[tuple[int, int, int]] = []
    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(tasks, "Bot", lambda token: fake_bot)
    monkeypatch.setattr(tasks, "datetime", FrozenDateTime)
    monkeypatch.setattr(
        tasks,
        "schedule_scheduled_announcement",
        lambda *, delay_seconds, group_id, entry_id: reschedules.append((delay_seconds, group_id, entry_id)),
    )
    monkeypatch.setattr(
        tasks,
        "schedule_bot_message_delete",
        lambda *, delay_seconds, chat_id, message_id: delete_calls.append((delay_seconds, chat_id, message_id)),
    )

    await tasks._run_scheduled_announcement(seeded_group["group_id"], "announcement-1")

    assert fake_bot.sent_messages == [(seeded_group["tg_group_id"], "Recurring reminder")]
    assert reschedules == [(810, seeded_group["group_id"], "announcement-1")]
    assert delete_calls == [(30, seeded_group["tg_group_id"], 1001)]

    async with session_factory() as session:
        saved = await SettingsService(session).get_one(seeded_group["group_id"], "announcement_schedules")
    assert saved[0]["status"] == "pending"
    assert saved[0]["send_at"] == "2026-03-13T12:00"


@pytest.mark.asyncio
async def test_run_scheduled_announcement_delegates_to_runtime_service(
    patch_db_dependencies,
    seeded_group,
    session_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with session_factory() as session:
        await SettingsService(session).set_value(
            seeded_group["group_id"],
            "announcement_schedules",
            [
                {
                    "id": "announcement-runtime-1",
                    "text": "Runtime reminder",
                    "send_at": "2026-03-13T11:45",
                    "status": "pending",
                }
            ],
        )

    runtime_calls: list[dict[str, object]] = []

    class FrozenDateTime(datetime):
        @classmethod
        def utcnow(cls) -> datetime:
            return cls(2026, 3, 13, 11, 46, 30)

    async def fake_execute(self, request, *, bot) -> dict[str, object]:
        runtime_calls.append({"request": request, "bot": bot})
        return {"status": "ok", "destination_message_id": 1001}

    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(tasks, "Bot", lambda token: fake_bot)
    monkeypatch.setattr(tasks, "datetime", FrozenDateTime)
    monkeypatch.setattr("bot.workers.tasks.AutomationRuntimeService.execute_scheduled_announcement", fake_execute)

    await tasks._run_scheduled_announcement(seeded_group["group_id"], "announcement-runtime-1")

    assert runtime_calls[0]["request"].entry_id == "announcement-runtime-1"
    assert runtime_calls[0]["request"].text == "Runtime reminder"
    assert runtime_calls[0]["bot"] is fake_bot


@pytest.mark.asyncio
async def test_on_group_message_logs_text_link_entity_as_link(
    patch_db_dependencies,
    patch_moderation_events_session,
    seeded_group,
    fake_message_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_events: list[tuple[str, dict[str, Any]]] = []

    monkeypatch.setattr("bot.handlers.moderation.events.run_spam_analysis.send", Mock())

    from bot.handlers.moderation import events as moderation_events

    monkeypatch.setattr(
        moderation_events.logger,
        "info",
        lambda event_name, **kwargs: log_events.append((event_name, kwargs)),
    )

    message = fake_message_factory(
        chat_id=seeded_group["tg_group_id"],
        chat_type="supergroup",
        user_id=seeded_group["user_id"],
        text="tap here",
        message_id=505,
        bot=fake_bot,
        entities=[SimpleNamespace(type="text_link", url="https://spam.example")],
    )

    await on_group_message(message, EventBus())

    assert ("moderation_message_trace", {
        "chat_id": seeded_group["tg_group_id"],
        "chat_type": "supergroup",
        "user_id": seeded_group["user_id"],
        "message_id": 505,
        "text": "tap here",
        "has_text": True,
        "contains_link": True,
        "entity_types": ["text_link"],
        "caption_entity_types": [],
    }) in log_events
    assert ("moderation_message_publish", {
        "chat_id": seeded_group["tg_group_id"],
        "chat_type": "supergroup",
        "user_id": seeded_group["user_id"],
        "message_id": 505,
        "contains_link": True,
        "text": "tap here",
    }) in log_events


@pytest.mark.asyncio
async def test_integration_message_plugin_worker_db(
    patch_db_dependencies,
    patch_moderation_events_session,
    seeded_group,
    db_session,
    fake_message_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Load plugin handler into bus, simulate incoming Telegram group message,
    # and assert downstream effects (worker dispatch + DB moderation log).
    bus = EventBus()
    from aiogram import Dispatcher
    from bot.core.plugin_manager import PluginManager

    manager = PluginManager()
    await manager.load_all(Dispatcher(), bus)

    send_mock = Mock()
    monkeypatch.setattr("bot.handlers.moderation.events.run_spam_analysis.send", send_mock)
    message = fake_message_factory(
        chat_id=seeded_group["tg_group_id"],
        chat_type="group",
        user_id=seeded_group["user_id"],
        text="go to https://malicious.example",
        message_id=501,
        bot=fake_bot,
    )

    await on_group_message(message, bus)

    send_mock.assert_called_once_with(
        seeded_group["tg_group_id"],
        501,
        seeded_group["user_id"],
        "go to https://malicious.example",
        "ar",
    )

    logs = (
        await db_session.execute(
            select(ModerationLog).where(ModerationLog.group_id == seeded_group["group_id"])
        )
    ).scalars().all()
    assert any(log.action == "delete_link" for log in logs)


@pytest.mark.asyncio
async def test_anti_spam_toggle_disables_worker_dispatch(
    patch_db_dependencies,
    patch_moderation_events_session,
    seeded_group,
    db_session,
    fake_message_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await SettingsService(db_session).set_value(seeded_group["group_id"], "anti_spam", False)

    send_mock = Mock()
    monkeypatch.setattr("bot.handlers.moderation.events.run_spam_analysis.send", send_mock)

    message = fake_message_factory(
        chat_id=seeded_group["tg_group_id"],
        chat_type="group",
        user_id=seeded_group["user_id"],
        text="normal message",
        message_id=502,
        bot=fake_bot,
    )

    await on_group_message(message, EventBus())

    send_mock.assert_not_called()


@pytest.mark.asyncio
async def test_anti_ads_sends_notice_after_deletion(
    patch_db_dependencies,
    patch_moderation_events_session,
    seeded_group,
    db_session,
    fake_message_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    classify = AsyncMock(return_value=SimpleNamespace(label="ad", ad_score=0.99))
    monkeypatch.setattr("bot.handlers.moderation.events.ads_service", SimpleNamespace(classify=classify))
    send_mock = Mock()
    monkeypatch.setattr("bot.handlers.moderation.events.run_spam_analysis.send", send_mock)

    message = fake_message_factory(
        chat_id=seeded_group["tg_group_id"],
        chat_type="group",
        user_id=seeded_group["user_id"],
        text="buy now",
        message_id=506,
        bot=fake_bot,
    )

    await on_group_message(message, EventBus())

    assert message.log.deletes == [{"chat_id": seeded_group["tg_group_id"], "message_id": 506}]
    assert fake_bot.sent_messages[-1] == (seeded_group["tg_group_id"], build_rule_notice("ar", "anti_ads"))
    logs = (
        await db_session.execute(
            select(ModerationLog).where(ModerationLog.group_id == seeded_group["group_id"])
        )
    ).scalars().all()
    assert any(log.action == "delete_ad" for log in logs)


@pytest.mark.asyncio
async def test_anti_ads_delete_delegates_to_runtime_facade(
    patch_db_dependencies,
    patch_moderation_events_session,
    seeded_group,
    fake_message_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_calls: list[dict[str, object]] = []

    async def fake_enforce(self, request, *, bot) -> dict[str, object]:
        runtime_calls.append({"request": request, "bot": bot})
        return {"status": "ok", "action": "delete_ad"}

    classify = AsyncMock(return_value=SimpleNamespace(label="ad", ad_score=0.99))
    monkeypatch.setattr("bot.handlers.moderation.events.ads_service", SimpleNamespace(classify=classify))
    monkeypatch.setattr("bot.handlers.moderation.events.run_spam_analysis.send", Mock())
    monkeypatch.setattr(
        "bot.handlers.moderation.events.ModerationRuntimeService.enforce_flagged_message",
        fake_enforce,
    )

    message = fake_message_factory(
        chat_id=seeded_group["tg_group_id"],
        chat_type="group",
        user_id=seeded_group["user_id"],
        text="buy now",
        message_id=5061,
        bot=fake_bot,
    )

    await on_group_message(message, EventBus())

    assert runtime_calls
    assert runtime_calls[0]["request"].delete_log_action == "delete_ad"
    assert runtime_calls[0]["request"].source == "anti_ads"


@pytest.mark.asyncio
async def test_anti_ads_can_mute_sender_after_deletion(
    patch_db_dependencies,
    patch_moderation_events_session,
    seeded_group,
    db_session,
    fake_message_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await SettingsService(db_session).set_value(seeded_group["group_id"], "anti_ads_mute", True)
    classify = AsyncMock(return_value=SimpleNamespace(label="ad", ad_score=0.99))
    monkeypatch.setattr("bot.handlers.moderation.events.ads_service", SimpleNamespace(classify=classify))
    monkeypatch.setattr("bot.handlers.moderation.events.run_spam_analysis.send", Mock())

    message = fake_message_factory(
        chat_id=seeded_group["tg_group_id"],
        chat_type="group",
        user_id=seeded_group["user_id"],
        text="buy now",
        message_id=507,
        bot=fake_bot,
    )

    await on_group_message(message, EventBus())

    assert fake_bot.muted_members == [(seeded_group["tg_group_id"], seeded_group["user_id"])]
    logs = (
        await db_session.execute(
            select(ModerationLog).where(ModerationLog.group_id == seeded_group["group_id"])
        )
    ).scalars().all()
    assert any(log.action == "mute_ad_user" for log in logs)


@pytest.mark.asyncio
async def test_anti_ads_skips_group_admin_messages(
    patch_db_dependencies,
    patch_moderation_events_session,
    seeded_group,
    db_session,
    fake_message_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    classify = AsyncMock(return_value=SimpleNamespace(label="ad", ad_score=0.99))
    monkeypatch.setattr("bot.handlers.moderation.events.ads_service", SimpleNamespace(classify=classify))
    monkeypatch.setattr("bot.handlers.moderation.events.run_spam_analysis.send", Mock())
    fake_bot.chat_members[(seeded_group["tg_group_id"], seeded_group["user_id"])] = SimpleNamespace(status="administrator")

    message = fake_message_factory(
        chat_id=seeded_group["tg_group_id"],
        chat_type="group",
        user_id=seeded_group["user_id"],
        text="buy now",
        message_id=5071,
        bot=fake_bot,
    )

    await on_group_message(message, EventBus())

    assert message.log.deletes == []
    assert message.log.answers == []
    assert fake_bot.muted_members == []
    logs = (
        await db_session.execute(
            select(ModerationLog).where(ModerationLog.group_id == seeded_group["group_id"])
        )
    ).scalars().all()
    assert not any(log.action == "delete_ad" and log.details.get("message_id") == 5071 for log in logs)


@pytest.mark.asyncio
async def test_anti_ads_respects_mute_threshold(
    patch_db_dependencies,
    patch_moderation_events_session,
    seeded_group,
    db_session,
    fake_message_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await SettingsService(db_session).set_value(seeded_group["group_id"], "anti_ads_mute", True)
    await SettingsService(db_session).set_value(seeded_group["group_id"], "anti_ads_mute_limit", 2)
    classify = AsyncMock(return_value=SimpleNamespace(label="ad", ad_score=0.99))
    monkeypatch.setattr("bot.handlers.moderation.events.ads_service", SimpleNamespace(classify=classify))
    monkeypatch.setattr("bot.handlers.moderation.events.run_spam_analysis.send", Mock())

    first = fake_message_factory(
        chat_id=seeded_group["tg_group_id"],
        chat_type="group",
        user_id=seeded_group["user_id"],
        text="buy now",
        message_id=508,
        bot=fake_bot,
    )
    await on_group_message(first, EventBus())
    assert fake_bot.muted_members == []

    second = fake_message_factory(
        chat_id=seeded_group["tg_group_id"],
        chat_type="group",
        user_id=seeded_group["user_id"],
        text="buy now again",
        message_id=509,
        bot=fake_bot,
    )
    await on_group_message(second, EventBus())
    assert fake_bot.muted_members == [(seeded_group["tg_group_id"], seeded_group["user_id"])]


@pytest.mark.asyncio
async def test_anti_ads_toggle_disables_classifier_deletion(
    patch_db_dependencies,
    patch_moderation_events_session,
    seeded_group,
    db_session,
    fake_message_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await SettingsService(db_session).set_value(seeded_group["group_id"], "anti_ads", False)

    classify = AsyncMock(return_value=SimpleNamespace(label="ad", ad_score=0.99))
    monkeypatch.setattr("bot.handlers.moderation.events.ads_service", SimpleNamespace(classify=classify))
    send_mock = Mock()
    monkeypatch.setattr("bot.handlers.moderation.events.run_spam_analysis.send", send_mock)

    message = fake_message_factory(
        chat_id=seeded_group["tg_group_id"],
        chat_type="group",
        user_id=seeded_group["user_id"],
        text="buy now",
        message_id=503,
        bot=fake_bot,
    )

    await on_group_message(message, EventBus())

    classify.assert_not_awaited()
    assert message.log.deletes == []
    logs = (
        await db_session.execute(
            select(ModerationLog).where(ModerationLog.group_id == seeded_group["group_id"])
        )
    ).scalars().all()
    assert not any(log.action == "delete_ad" for log in logs)


@pytest.mark.integration
def test_redis_service_integration() -> None:
    if os.getenv("RUN_INTEGRATION") != "1":
        pytest.skip("set RUN_INTEGRATION=1 to run Redis-backed integration tests")

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    client = Redis.from_url(redis_url, decode_responses=True)

    last_error: Exception | None = None
    for _ in range(10):
        try:
            assert client.ping() is True
            client.set("integration:smoke", "ok", ex=30)
            assert client.get("integration:smoke") == "ok"
            return
        except Exception as exc:
            last_error = exc
            time.sleep(1)
    raise AssertionError(f"Redis integration check failed for {redis_url}: {last_error}")
