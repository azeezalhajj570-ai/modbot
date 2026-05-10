from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select

from bot.core.runtime.actions import AddWarningAction, ClearWarningsAction, DeleteMessageAction
from bot.core.runtime.admin import AdminAutomationRuntimeService
from bot.core.runtime.audit import AuditEntry, ModerationLogAuditSink, parse_runtime_audit_compatibility
from bot.core.runtime.replay import RuntimeReplayService
from bot.core.runtime.automation import ScheduledAnnouncementRequest
from bot.core.runtime.events import RuntimeEvent, RuntimeEventType
from bot.core.runtime.executors import ActionExecutorRegistry
from bot.core.runtime.guards import GuardDecision, GuardPipeline, GuardResult
from bot.core.runtime.moderation import FlaggedWarningModerationRequest, ModerationRuntimeService
from bot.agents.runtime import AgentTaskRuntime
from bot.automation.executors import AgentJobExecutor
from bot.automation.models import TaskAssignment, TaskDefinition, TaskEvent
from bot.automation.registry import build_default_registry
from bot.dashboard.api import main as api_main
from bot.db.models import Agent, AgentJob, Group, GroupAdminRole, ModerationLog, User, Warning
from bot.main import run_bot
from bot.agents.agent_job_service import AgentJobService
from bot.services.scheduled_message_store import ScheduledMessageEntry, ScheduledMessageStore
from bot.services.task_assignment_store import TaskAssignmentStore
from bot.services.task_service import TaskService


@pytest.mark.asyncio
async def test_dashboard_api_startup_runs_schema_bootstrap_only_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema = AsyncMock()
    monkeypatch.setattr(api_main, "ensure_schema", ensure_schema)
    monkeypatch.setattr(api_main, "get_settings", lambda: SimpleNamespace(run_schema_bootstrap=True))

    await api_main.on_startup()

    ensure_schema.assert_awaited_once_with(api_main.engine)

    ensure_schema.reset_mock()
    monkeypatch.setattr(api_main, "get_settings", lambda: SimpleNamespace(run_schema_bootstrap=False))

    await api_main.on_startup()

    ensure_schema.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_bot_wires_runtime_dependencies_without_bootstrap_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(
        log_level="INFO",
        aiogram_log_level="warning",
        sentry_dsn="",
        run_schema_bootstrap=False,
        bot_app_kind="admin",
        bot_token="123456:TESTTOKEN",
        resolve_bot_token=Mock(return_value="123456:TESTTOKEN"),
        redis_url="redis://redis:6379/0",
        telegram_request_timeout=15,
        log_raw_updates=False,
        telegram_polling_timeout=33,
    )
    fake_redis = SimpleNamespace(aclose=AsyncMock())
    fake_bot = SimpleNamespace(delete_webhook=AsyncMock())
    fake_dispatcher = SimpleNamespace(
        update=SimpleNamespace(outer_middleware=Mock()),
        include_router=Mock(),
        start_polling=AsyncMock(),
        storage=SimpleNamespace(close=AsyncMock()),
    )
    fake_event_bus = object()
    fake_menu_engine = object()
    fake_plugin_manager = SimpleNamespace(load_all=AsyncMock())
    router = object()
    ensure_schema = AsyncMock()
    configure_menu = AsyncMock()

    monkeypatch.setattr("bot.main.get_settings", lambda: settings)
    monkeypatch.setattr("bot.main.configure_logging", Mock())
    monkeypatch.setattr("bot.main.ensure_schema", ensure_schema)
    monkeypatch.setattr("bot.main.AiohttpSession", Mock(return_value=object()))
    monkeypatch.setattr("bot.main.Bot", Mock(return_value=fake_bot))
    monkeypatch.setattr("bot.main.Redis.from_url", Mock(return_value=fake_redis))
    monkeypatch.setattr("bot.main.RedisStorage", Mock(return_value=object()))
    monkeypatch.setattr("bot.main.Dispatcher", Mock(return_value=fake_dispatcher))
    monkeypatch.setattr("bot.main.EventBus", Mock(return_value=fake_event_bus))
    monkeypatch.setattr("bot.main.MenuEngine", Mock(return_value=fake_menu_engine))
    monkeypatch.setattr("bot.main.PluginManager", Mock(return_value=fake_plugin_manager))
    monkeypatch.setattr("bot.main.build_router", Mock(return_value=router))
    monkeypatch.setattr("bot.main._configure_chat_menu_button", configure_menu)
    monkeypatch.setattr("bot.main._configure_bot_commands", AsyncMock())
    monkeypatch.setattr("bot.main.AgentListenerManager", Mock(return_value=SimpleNamespace(start=AsyncMock(), stop=AsyncMock())))

    await run_bot()

    ensure_schema.assert_not_awaited()
    settings.resolve_bot_token.assert_called_once_with("admin")
    fake_bot.delete_webhook.assert_awaited_once_with(drop_pending_updates=False)
    configure_menu.assert_awaited_once_with(fake_bot, settings)
    fake_dispatcher.include_router.assert_called_once_with(router)
    fake_plugin_manager.load_all.assert_awaited_once_with(fake_dispatcher, fake_event_bus)
    fake_dispatcher.start_polling.assert_awaited_once_with(
        fake_bot,
        polling_timeout=33,
        event_bus=fake_event_bus,
        menu_engine=fake_menu_engine,
        plugin_manager=fake_plugin_manager,
        redis=fake_redis,
    )
    fake_dispatcher.storage.close.assert_awaited_once()
    fake_redis.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_agent_job_executor_persists_job_payload_and_awaits_async_dispatch(
    db_session,
) -> None:
    user = User(tg_user_id=9301, username="owner9301", full_name="Owner 9301", language_code="en")
    db_session.add(user)
    await db_session.flush()
    group = Group(tg_group_id=-1009301, title="Executor Group", owner_user_id=user.id, is_active=True)
    db_session.add(group)
    await db_session.flush()
    agent = Agent(
        group_id=group.id,
        telegram_user_id=9302,
        external_account_id="executor-agent",
        status="active",
        auth_state="active",
        session_string="session-executor",
        details={},
    )
    db_session.add(agent)
    await db_session.commit()

    handler = AsyncMock(return_value={"text": "Boundary hello"})
    task = TaskDefinition(
        key="reply_message",
        title="Reply",
        description="Reply",
        trigger="message.received",
        config_schema={},
        handler=handler,
    )
    assignment = TaskAssignment(
        assignment_id="assignment-executor",
        task_key="reply_message",
        executor_type="agent",
        config={"message_template": "Boundary hello"},
        agent_id=agent.id,
    )
    event = TaskEvent(
        name="message.received",
        group_id=group.id,
        user_id=user.tg_user_id,
        payload={"chat_id": group.tg_group_id, "text": "hello", "message_id": 73, "first_name": "Owner"},
    )
    dispatch_job = AsyncMock()
    executor = AgentJobExecutor(job_service=AgentJobService(db_session), dispatch_job=dispatch_job)

    result = await executor.execute(task, assignment, event)

    job = (await db_session.execute(select(AgentJob).where(AgentJob.id == result["job_id"]))).scalar_one()
    assert result == {"job_id": job.id, "status": "pending"}
    assert job.job_type == "automation_task"
    assert job.job_payload["assignment_id"] == "assignment-executor"
    assert job.job_payload["event"]["payload"]["chat_id"] == group.tg_group_id
    assert job.job_payload["event"]["payload"]["text"] == "hello"
    dispatch_job.assert_awaited_once_with(job.id)


@pytest.mark.asyncio
async def test_runtime_replay_service_normalizes_runtime_audit_record(db_session) -> None:
    log = ModerationLog(
        group_id=901,
        action="destination_notified",
        target_user_id=44,
        admin_user_id=11,
        reason="pricing",
        details={
            "domain": "automation",
            "runtime_event": "automation.notify_destination_requested",
            "runtime_action": "send_runtime_message",
            "source_runtime": "automation.runtime",
            "correlation_id": "corr-1",
            "subject_type": "task_assignment",
            "subject_id": "assignment-1",
            "selected_actions": ["send_runtime_message"],
            "guard_outcomes": [{"decision": "allow", "reason": None, "details": {}}],
            "execution_result": {"chat_id": 123456, "destination_message_id": 1001},
            "compat_schema_version": 1,
        },
    )
    db_session.add(log)
    await db_session.commit()

    record = await RuntimeReplayService(db_session).get_record(log_id=log.id)

    assert record is not None
    assert record.runtime_event == "automation.notify_destination_requested"
    assert record.selected_actions == ["send_runtime_message"]
    assert record.execution_result["destination_message_id"] == 1001
    assert record.audit_result["target_user_id"] == 44
    assert record.audit_result["compat_schema_version"] == 1


@pytest.mark.asyncio
async def test_runtime_audit_compatibility_parser_falls_back_to_runtime_action_and_extra_details(db_session) -> None:
    log = ModerationLog(
        group_id=902,
        action="warn_spam",
        target_user_id=55,
        admin_user_id=10,
        reason="spam",
        details={
            "domain": "moderation",
            "runtime_event": "moderation.warning_triggered",
            "runtime_action": "add_warning",
            "source_runtime": "moderation.runtime",
            "compat_schema_version": "1",
            "message_id": 333,
            "notice_sent": True,
        },
    )
    db_session.add(log)
    await db_session.commit()

    parsed = parse_runtime_audit_compatibility(log)

    assert parsed.is_runtime_audit is True
    assert parsed.selected_actions == ["add_warning"]
    assert parsed.execution_result == {"message_id": 333, "notice_sent": True}
    assert parsed.compat_schema_version == 1


@pytest.mark.asyncio
async def test_agent_task_runtime_schedules_follow_up_from_loaded_job(
    monkeypatch: pytest.MonkeyPatch,
    session_factory,
    db_session,
) -> None:
    user = User(tg_user_id=9401, username="owner9401", full_name="Owner 9401", language_code="en")
    db_session.add(user)
    await db_session.flush()
    group = Group(tg_group_id=-1009401, title="Runtime Follow Up Group", owner_user_id=user.id, is_active=True)
    db_session.add(group)
    await db_session.flush()
    agent = Agent(
        group_id=group.id,
        telegram_user_id=9402,
        external_account_id="runtime-follow-up-agent",
        status="active",
        auth_state="active",
        session_string="session-follow-up",
        details={},
    )
    db_session.add(agent)
    await db_session.flush()
    job = AgentJob(
        agent_id=agent.id,
        job_type="automation_task",
        job_payload={
            "task_key": "welcome_flow",
            "assignment_id": "assignment-follow-up",
            "task_config": {
                "message_template": "Welcome {first_name}",
                "scheduled_follow_up_message": "Later hello {first_name}",
                "follow_up_delay_seconds": 120,
                "follow_up_delete_after_seconds": 45,
            },
            "event": {
                "name": "member.joined",
                "group_id": group.id,
                "user_id": user.tg_user_id,
                "payload": {
                    "chat_id": group.tg_group_id,
                    "message_id": 91,
                    "first_name": "Owner",
                },
            },
        },
        status="pending",
    )
    db_session.add(job)
    await db_session.commit()

    dispatch_calls: list[dict[str, int | str | None]] = []
    monkeypatch.setattr("bot.agents.runtime.SessionLocal", session_factory)
    runtime = AgentTaskRuntime(
        registry=build_default_registry(),
        executor=SimpleNamespace(execute=AsyncMock(return_value={"ok": True})),
        dispatch_follow_up=lambda **kwargs: dispatch_calls.append(kwargs),
    )

    dispatched = await runtime.dispatch_job(job.id)

    async with session_factory() as verification_session:
        stored = (await verification_session.execute(select(AgentJob).where(AgentJob.id == job.id))).scalar_one()
        logs = (
            await verification_session.execute(
                select(ModerationLog).where(ModerationLog.group_id == group.id).order_by(ModerationLog.id.asc())
            )
        ).scalars().all()

    assert dispatched is True
    assert stored.status == "completed"
    assert dispatch_calls == [
        {
            "delay_seconds": 120,
            "group_id": group.id,
            "chat_id": group.tg_group_id,
            "executor_type": "agent",
            "agent_id": agent.id,
            "text": "Later hello Owner",
            "assignment_id": "assignment-follow-up",
            "task_key": "welcome_flow",
            "target_user_id": user.tg_user_id,
            "delete_after_seconds": 45,
        }
    ]
    assert [log.action for log in logs] == ["welcome_flow_sent", "task_follow_up_scheduled"]


@pytest.mark.asyncio
async def test_action_executor_registry_dispatches_registered_executor() -> None:
    calls: list[int] = []

    async def execute_delete(action) -> dict[str, object]:
        calls.append(action.message_id)
        return {"deleted": True}

    registry = ActionExecutorRegistry()
    registry.register("delete_message", execute_delete)
    result = await registry.execute(
        DeleteMessageAction(
            kind="delete_message",
            group_id=1,
            chat_id=-1001,
            message_id=77,
            target_user_id=901,
        )
    )

    assert result == {"deleted": True}
    assert calls == [77]


@pytest.mark.asyncio
async def test_moderation_log_audit_sink_persists_compatibility_row(db_session) -> None:
    group = Group(tg_group_id=-1009942, title="Audit Sink Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    sink = ModerationLogAuditSink(db_session)

    await sink.write(
        AuditEntry(
            action="delete_spam",
            group_id=group.id,
            actor_user_id=None,
            target_user_id=902,
            reason="spam",
            details={"message_id": 90},
        )
    )
    await db_session.commit()

    log = (
        await db_session.execute(
            select(ModerationLog).where(
                ModerationLog.group_id == group.id,
                ModerationLog.action == "delete_spam",
            )
        )
    ).scalar_one()
    assert log.target_user_id == 902
    assert log.details["message_id"] == 90
    assert log.details["domain"] == "moderation"
    assert log.details["source_runtime"] == "runtime"
    assert log.details["runtime_action"] == "delete_spam"


@pytest.mark.asyncio
async def test_moderation_log_audit_sink_records_runtime_envelope(db_session) -> None:
    group = Group(tg_group_id=-1009943, title="Audit Envelope Group", is_active=True)
    db_session.add(group)
    await db_session.flush()

    await ModerationLogAuditSink(db_session).write(
        AuditEntry(
            action="warn_spam",
            action_type="add_warning",
            event_type=RuntimeEventType.MODERATION_WARNING_TRIGGERED,
            group_id=group.id,
            actor_user_id=None,
            target_user_id=812,
            subject_type="user",
            subject_id="812",
            source_runtime="moderation.runtime",
            correlation_id="corr-123",
            details={"message_id": 44},
        )
    )
    await db_session.commit()

    log = (
        await db_session.execute(
            select(ModerationLog).where(
                ModerationLog.group_id == group.id,
                ModerationLog.action == "warn_spam",
            )
        )
    ).scalar_one()
    assert log.details["runtime_event"] == RuntimeEventType.MODERATION_WARNING_TRIGGERED
    assert log.details["runtime_action"] == "add_warning"
    assert log.details["correlation_id"] == "corr-123"
    assert log.details["subject_id"] == "812"


@pytest.mark.asyncio
async def test_action_executor_registry_dispatches_warning_clear_actions() -> None:
    calls: list[tuple[str, int]] = []

    async def execute_add(action) -> dict[str, object]:
        calls.append((action.kind, action.target_user_id))
        return {"count": action.count}

    async def execute_clear(action) -> dict[str, object]:
        calls.append((action.kind, action.target_user_id))
        return {"deleted": 2}

    registry = ActionExecutorRegistry()
    registry.register("add_warning", execute_add)
    registry.register("clear_warnings", execute_clear)

    add_result = await registry.execute(
        AddWarningAction(
            kind="add_warning",
            group_id=1,
            actor_user_id=9,
            target_user_id=77,
            reason="spam",
            count=2,
        )
    )
    clear_result = await registry.execute(
        ClearWarningsAction(
            kind="clear_warnings",
            group_id=1,
            actor_user_id=9,
            target_user_id=77,
        )
    )

    assert add_result == {"count": 2}
    assert clear_result == {"deleted": 2}
    assert calls == [("add_warning", 77), ("clear_warnings", 77)]


@pytest.mark.asyncio
async def test_runtime_warn_flow_persists_warning_and_runtime_audit(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group = Group(tg_group_id=-1009944, title="Runtime Warn Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=51, role="owner"))
    await db_session.commit()

    fake_bot = SimpleNamespace(
        ban_chat_member=AsyncMock(),
        restrict_chat_member=AsyncMock(),
        session=SimpleNamespace(close=AsyncMock()),
    )
    monkeypatch.setattr("bot.core.runtime.moderation.Bot", lambda token: fake_bot)

    result = await ModerationRuntimeService(db_session).add_warning(
        group_id=group.id,
        actor_user_id=51,
        user_id=88,
        reason="spam",
        count=1,
    )

    warning = (
        await db_session.execute(select(Warning).where(Warning.group_id == group.id, Warning.user_id == 88))
    ).scalar_one()
    logs = (
        await db_session.execute(select(ModerationLog).where(ModerationLog.group_id == group.id).order_by(ModerationLog.id.asc()))
    ).scalars().all()

    assert result == {"status": "ok", "count": 1}
    assert warning.count == 1
    assert logs[-1].action == "warn"
    assert logs[-1].details["runtime_action"] == "add_warning"


@pytest.mark.asyncio
async def test_runtime_flagged_warning_flow_uses_runtime_path(db_session) -> None:
    group = Group(tg_group_id=-1009945, title="Flagged Warn Group", is_active=True)
    db_session.add(group)
    await db_session.flush()

    fake_bot = SimpleNamespace(
        ban_chat_member=AsyncMock(),
        restrict_chat_member=AsyncMock(),
        send_message=AsyncMock(),
    )

    result = await ModerationRuntimeService(db_session).enforce_flagged_warning(
        FlaggedWarningModerationRequest(
            group_id=group.id,
            chat_id=group.tg_group_id,
            target_user_id=99,
            source="anti_spam",
            reason="promo",
            score=0.7,
            notice_key="anti_spam_warn",
            log_action="warn_spam",
            lang="en",
            metadata={"message_id": 501},
        ),
        bot=fake_bot,
    )

    warning = (
        await db_session.execute(select(Warning).where(Warning.group_id == group.id, Warning.user_id == 99))
    ).scalar_one()
    log = (
        await db_session.execute(select(ModerationLog).where(ModerationLog.group_id == group.id, ModerationLog.action == "warn_spam"))
    ).scalar_one()

    assert result["action"] == "warn_spam"
    assert warning.count == 1
    assert log.details["runtime_event"] == RuntimeEventType.MODERATION_WARNING_TRIGGERED


@pytest.mark.asyncio
async def test_task_assignment_store_round_trips_current_group_setting_shape(db_session) -> None:
    group = Group(tg_group_id=-1004101, title="Task Store Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    store = TaskAssignmentStore(db_session)
    assignment = TaskAssignment(
        assignment_id="assignment-store-1",
        task_key="reply_message",
        executor_type="bot",
        conditions={"text_contains": "pricing"},
        config={"message_template": "Support will reply"},
    )

    await store.upsert_assignment(group.id, assignment)
    loaded = await store.list_assignments(group.id)

    assert loaded == [assignment]
    assert TaskAssignmentStore.serialize_assignment(loaded[0], group_id=group.id)["task_key"] == "reply_message"


@pytest.mark.asyncio
async def test_scheduled_message_store_round_trips_current_group_setting_shape(db_session) -> None:
    group = Group(tg_group_id=-1004201, title="Schedule Store Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    store = ScheduledMessageStore(db_session)
    entry = ScheduledMessageEntry(
        id="schedule-store-1",
        text="Reminder",
        send_at="2026-04-20T11:45",
        status="pending",
        cron="*/15 * * * *",
        delete_after_seconds=30,
    )

    await store.save_entry(group.id, entry)
    loaded = await store.get_entry(group.id, "schedule-store-1")

    assert loaded == entry


@pytest.mark.asyncio
async def test_task_service_keyword_reply_delegates_to_automation_runtime(
    db_session,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group = Group(tg_group_id=-1001001, title="Keyword Runtime Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=1, role="owner"))
    await db_session.commit()

    service = TaskService(
        db_session,
        dispatch_agent_job=AsyncMock(),
        dispatch_delete_message=Mock(),
    )
    runtime_calls: list[dict[str, object]] = []

    async def fake_execute(self, request, *, bot) -> dict[str, object]:
        runtime_calls.append({"request": request, "bot": bot})
        return {"status": "ok", "destination_message_id": 77}

    monkeypatch.setattr("bot.automation.executors.AutomationRuntimeService.execute_keyword_reply", fake_execute)

    await service.save_assignment(
        actor_user_id=1,
        group_id=group.id,
        task_key="reply_message",
        executor_type="bot",
        enabled=True,
        conditions={"text_contains": "price"},
        config={"message_template": "Pricing team will reply soon."},
        agent_id=None,
        assignment_id="assignment-keyword-1",
    )

    outputs = await service.handle_message_event(
        group_id=group.id,
        user_id=99,
        payload={"chat_id": group.tg_group_id, "text": "price please", "message_id": 55, "bot": fake_bot},
    )

    assert outputs == [{"status": "ok", "destination_message_id": 77}]
    assert runtime_calls[0]["request"].task_key == "reply_message"
    assert runtime_calls[0]["request"].reply_to_message_id == 55
    assert runtime_calls[0]["bot"] is fake_bot


@pytest.mark.asyncio
async def test_task_service_notify_destination_delegates_to_automation_runtime(
    db_session,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group = Group(tg_group_id=-1001002, title="Notify Runtime Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=1, role="owner"))
    await db_session.commit()

    service = TaskService(
        db_session,
        dispatch_agent_job=AsyncMock(),
        dispatch_delete_message=Mock(),
    )
    runtime_calls: list[dict[str, object]] = []

    async def fake_execute(self, request, *, bot) -> dict[str, object]:
        runtime_calls.append({"request": request, "bot": bot})
        return {
            "status": "ok",
            "chat_id": 123456,
            "destination_message_id": 88,
            "forwarded_message_id": 89,
        }

    monkeypatch.setattr("bot.automation.executors.AutomationRuntimeService.execute_notify_destination", fake_execute)

    await service.save_assignment(
        actor_user_id=1,
        group_id=group.id,
        task_key="notify_destination",
        executor_type="bot",
        enabled=True,
        conditions={"text_contains": "urgent"},
        config={
            "message_template": "Alert: {text}",
            "destination": "123456",
            "delivery_mode": "text_and_forward",
            "delete_after_seconds": 30,
        },
        agent_id=None,
        assignment_id="assignment-notify-1",
    )

    outputs = await service.handle_message_event(
        group_id=group.id,
        user_id=99,
        payload={
            "chat_id": group.tg_group_id,
            "group_title": "Notify Runtime Group",
            "text": "urgent ticket",
            "message_id": 55,
            "bot": fake_bot,
        },
    )

    assert runtime_calls[0]["request"].task_key == "notify_destination"
    assert runtime_calls[0]["request"].forward_message_id == 55
    assert runtime_calls[0]["request"].delete_after_seconds == 30
    assert runtime_calls[0]["bot"] is fake_bot
    assert outputs == [
        {
            "status": "ok",
            "chat_id": 123456,
            "destination_message_id": 88,
            "forwarded_message_id": 89,
        }
    ]


@pytest.mark.asyncio
async def test_admin_runtime_builds_scheduled_announcement_request(db_session) -> None:
    runtime = AdminAutomationRuntimeService(db_session, dispatch_agent_job=AsyncMock())
    request = runtime.build_scheduled_announcement_request(
        group_id=12,
        entry_id="entry-1",
        chat_id=-10012,
        text="Scheduled hello",
        delete_after_seconds=15,
    )

    assert isinstance(request, ScheduledAnnouncementRequest)
    assert request.entry_id == "entry-1"
    assert request.delete_after_seconds == 15


@pytest.mark.asyncio
async def test_admin_runtime_loads_scheduled_dispatch_request(db_session) -> None:
    group = Group(tg_group_id=-1002001, title="Scheduled Runtime Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    await ScheduledMessageStore(db_session).save_entry(
        group.id,
        ScheduledMessageEntry(
            id="entry-2",
            text="Scheduled runtime hello",
            send_at="2026-03-13T11:45",
            status="pending",
            cron="*/15 * * * *",
            delete_after_seconds=60,
        ),
    )
    await db_session.commit()

    runtime = AdminAutomationRuntimeService(db_session, dispatch_agent_job=AsyncMock())
    request = await runtime.get_scheduled_message_dispatch_request(group_id=group.id, entry_id="entry-2")

    assert isinstance(request, ScheduledAnnouncementRequest)
    assert request.entry_id == "entry-2"
    assert request.chat_id == group.tg_group_id
    assert request.metadata == {"cron": "*/15 * * * *"}


@pytest.mark.asyncio
async def test_admin_runtime_forwards_agent_group_binding_fields(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_save_assignment(self, **kwargs):
        captured.update(kwargs)
        return {"assignment_id": "assignment-1"}

    monkeypatch.setattr(TaskService, "save_assignment", fake_save_assignment)
    runtime = AdminAutomationRuntimeService(db_session, dispatch_agent_job=AsyncMock())

    payload = await runtime.save_assignment(
        actor_user_id=10,
        group_id=11,
        assignment_id="assignment-1",
        task_key="reply_message",
        executor_type="agent",
        enabled=True,
        conditions={"text_contains": "support"},
        config={"message_template": "hello"},
        agent_id=12,
        group_ids=[11],
        group_tg_ids=[-10011],
        group_titles=["Ops Group"],
    )

    assert payload == {"assignment_id": "assignment-1"}
    assert captured["group_ids"] == [11]
    assert captured["group_tg_ids"] == [-10011]
    assert captured["group_titles"] == ["Ops Group"]


@pytest.mark.asyncio
async def test_guard_pipeline_denies_flagged_message_when_guard_blocks() -> None:
    class DenyGuard:
        async def evaluate(self, event, action) -> GuardResult:
            del action
            assert event.name == RuntimeEventType.MODERATION_MESSAGE_FLAGGED
            return GuardResult(decision=GuardDecision.DENY, reason="blocked")

    pipeline = GuardPipeline(guards=[DenyGuard()])
    result = await pipeline.evaluate(
        RuntimeEvent(
            name=RuntimeEventType.MODERATION_MESSAGE_FLAGGED,
            group_id=1,
            actor_user_id=None,
            payload={"source": "anti_spam"},
        ),
        DeleteMessageAction(
            kind="delete_message",
            group_id=1,
            chat_id=-1001,
            message_id=10,
            target_user_id=11,
        ),
    )

    assert result.decision == GuardDecision.DENY
    assert result.reason == "blocked"
