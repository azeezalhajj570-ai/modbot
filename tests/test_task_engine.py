from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy import select

from bot.agents.exceptions import AgentSessionError
from bot.agents.runtime import AgentTaskRuntime, GroupMemberBroadcastRuntime, ScraperRuntime
from bot.agents.worker import execute_agent_job
from bot.automation.agent_task_store import AgentTaskStore
from bot.automation.conditions import ConditionEvaluator
from bot.automation.engine import TaskEngine
from bot.automation.executors import BotTaskExecutor
from bot.automation.models import ActionTemplate, TaskAssignment, TaskCondition, TaskEvent, TaskTrigger
from bot.automation.planners import RulesPlanner
from bot.automation.registry import build_default_registry
from bot.db.models import Agent, AgentJob, Group, GroupAdminRole, ModerationLog, User
from bot.services.task_service import TaskService


@pytest.mark.asyncio
async def test_task_engine_filters_by_trigger_and_conditions_then_executes_action(fake_bot) -> None:
    registry = build_default_registry()
    engine = TaskEngine(registry=registry, condition_evaluator=ConditionEvaluator())
    assignment = TaskAssignment(
        assignment_id="task-1",
        task_key="reply_message",
        executor_type="bot",
        conditions={"text_contains": "help"},
        config={"message_template": "Support: {text}"},
    )

    results = await engine.process(
        [assignment],
        TaskEvent(
            name="message.received",
            group_id=-1001,
            user_id=50,
            payload={"text": "need help now", "message_id": 77, "bot": fake_bot},
        ),
        {"bot": BotTaskExecutor()},
    )

    assert results[0].output == {"text": "Support: need help now", "reply_to_message_id": 77}
    assert results[0].plan is not None
    assert results[0].plan.action_template.kind == "send_runtime_message"
    assert fake_bot.sent_messages == [(-1001, "Support: need help now")]


@pytest.mark.asyncio
async def test_task_engine_private_reply_targets_user_chat(fake_bot) -> None:
    registry = build_default_registry()
    engine = TaskEngine(registry=registry, condition_evaluator=ConditionEvaluator())
    assignment = TaskAssignment(
        assignment_id="task-private-1",
        task_key="reply_message",
        executor_type="bot",
        conditions={"text_contains": "help"},
        config={"message_template": "Support: private follow-up", "reply_mode": "private"},
    )

    results = await engine.process(
        [assignment],
        TaskEvent(
            name="message.received",
            group_id=-1001,
            user_id=5555,
            payload={"text": "need help now", "message_id": 77, "bot": fake_bot},
        ),
        {"bot": BotTaskExecutor()},
    )

    assert results[0].output == {"text": "Support: private follow-up", "chat_id": 5555}
    assert fake_bot.sent_messages == [(5555, "Support: private follow-up")]


@pytest.mark.asyncio
async def test_task_engine_reply_message_supports_inline_url_buttons(fake_bot) -> None:
    registry = build_default_registry()
    engine = TaskEngine(registry=registry, condition_evaluator=ConditionEvaluator())
    assignment = TaskAssignment(
        assignment_id="task-inline-1",
        task_key="reply_message",
        executor_type="bot",
        conditions={"text_contains": "pricing"},
        config={
            "message_template": "Open the options below.",
            "inline_buttons": [
                {"text": "Dashboard", "url": "https://example.com/dashboard"},
                {"text": "Docs", "url": "https://example.com/docs"},
            ],
        },
    )

    results = await engine.process(
        [assignment],
        TaskEvent(
            name="message.received",
            group_id=-1001,
            user_id=50,
            payload={"text": "pricing details", "message_id": 88, "bot": fake_bot},
        ),
        {"bot": BotTaskExecutor()},
    )

    markup = results[0].output.get("reply_markup")
    assert isinstance(markup, InlineKeyboardMarkup)
    assert [button.text for row in markup.inline_keyboard for button in row] == ["Dashboard", "Docs"]
    assert [button.url for row in markup.inline_keyboard for button in row] == [
        "https://example.com/dashboard",
        "https://example.com/docs",
    ]
    assert fake_bot.sent_message_payloads[0]["reply_markup"] == markup


@pytest.mark.asyncio
async def test_task_engine_executes_lead_capture_module(fake_bot) -> None:
    registry = build_default_registry()
    engine = TaskEngine(registry=registry, condition_evaluator=ConditionEvaluator())
    assignment = TaskAssignment(
        assignment_id="task-2",
        task_key="lead_capture",
        executor_type="bot",
        conditions={"text_contains": "quote"},
        config={"ack_template": "Thanks, we received your request.", "lead_label": "sales", "ask_contact": True},
    )

    results = await engine.process(
        [assignment],
        TaskEvent(
            name="message.received",
            group_id=-1002,
            user_id=51,
            payload={"text": "need a quote", "message_id": 78, "bot": fake_bot},
        ),
        {"bot": BotTaskExecutor()},
    )

    assert results[0].output["metadata"]["lead_label"] == "sales"
    assert fake_bot.sent_messages == [(-1002, "Thanks, we received your request.\n\nPlease share your preferred contact details.")]


def test_registry_contains_builtin_task_modules() -> None:
    registry = build_default_registry()
    keys = {definition.key for definition in registry.list()}
    assert {"reply_message", "welcome_flow", "lead_capture", "escalation_alert", "notify_destination"} <= keys
    notify_definition = registry.get("notify_destination")
    assert notify_definition.trigger_rule == TaskTrigger(event_name="message.received")
    assert notify_definition.action_template == ActionTemplate(
        kind="send_runtime_message",
        metadata={"flow": "notify_destination"},
    )


def test_condition_evaluator_matches_any_bulk_keyword() -> None:
    evaluator = ConditionEvaluator()
    event = TaskEvent(name="message.received", group_id=-1001, user_id=50, payload={"text": "need urgent sev1 support"})

    assert evaluator.matches(event, {"text_contains_any": ["vip", "sev1"]}) is True
    assert evaluator.matches(event, {"text_contains": ["vip", "urgent"]}) is True
    assert evaluator.matches(event, {"text_contains_any": ["vip", "billing"]}) is False


def test_rules_planner_builds_condition_and_action_templates() -> None:
    registry = build_default_registry()
    assignment = TaskAssignment(
        assignment_id="task-plan-1",
        task_key="reply_message",
        executor_type="bot",
        conditions={"text_contains": "help"},
        config={"message_template": "Support: {text}"},
    )
    event = TaskEvent(name="message.received", group_id=-1001, user_id=50, payload={"text": "need help now"})

    plan = RulesPlanner().plan(task=registry.get("reply_message"), assignment=assignment, event=event)

    assert plan is not None
    assert plan.context.trigger == TaskTrigger(event_name="message.received")
    assert plan.context.conditions == [TaskCondition(key="text_contains", value="help", operator="contains")]
    assert plan.action_template == ActionTemplate(kind="send_runtime_message", metadata={"flow": "reply_message"})


@pytest.mark.asyncio
async def test_task_engine_executes_notify_destination_module(fake_bot) -> None:
    registry = build_default_registry()
    engine = TaskEngine(registry=registry, condition_evaluator=ConditionEvaluator())
    assignment = TaskAssignment(
        assignment_id="task-notify-1",
        task_key="notify_destination",
        executor_type="bot",
        conditions={"text_contains": "urgent"},
        config={"message_template": "Alert: {text}", "destination": "123456", "delete_after_seconds": 30},
    )
    delete_calls: list[tuple[int, int, int]] = []

    results = await engine.process(
        [assignment],
        TaskEvent(
            name="message.received",
            group_id=-1008,
            user_id=42,
            payload={"chat_id": -1008, "group_title": "QA Group", "text": "urgent ticket", "message_id": 81, "bot": fake_bot},
        ),
        {
            "bot": BotTaskExecutor(
                dispatch_delete_message=lambda *, delay_seconds, chat_id, message_id: delete_calls.append(
                    (delay_seconds, chat_id, message_id)
                )
            )
        },
    )

    assert results[0].output["chat_id"] == 123456
    assert results[0].output["metadata"]["source_chat_id"] == "-1008"
    assert results[0].output["metadata"]["source_group_title"] == "QA Group"
    assert results[0].output["metadata"]["source_message_id"] == "81"
    assert fake_bot.sent_messages == [(123456, "[QA Group] Alert: urgent ticket")]
    assert delete_calls == [(30, 123456, 1001)]


@pytest.mark.asyncio
async def test_task_engine_can_forward_original_message_in_notify_destination(fake_bot) -> None:
    registry = build_default_registry()
    engine = TaskEngine(registry=registry, condition_evaluator=ConditionEvaluator())
    assignment = TaskAssignment(
        assignment_id="task-notify-forward-1",
        task_key="notify_destination",
        executor_type="bot",
        conditions={"text_contains": "urgent"},
        config={
            "message_template": "Alert: {text}",
            "destination": "123456",
            "delivery_mode": "text_and_forward",
            "delete_after_seconds": 30,
        },
    )
    delete_calls: list[tuple[int, int, int]] = []

    results = await engine.process(
        [assignment],
        TaskEvent(
            name="message.received",
            group_id=-1008,
            user_id=42,
            payload={"chat_id": -1008, "group_title": "QA Group", "text": "urgent ticket", "message_id": 81, "bot": fake_bot},
        ),
        {
            "bot": BotTaskExecutor(
                dispatch_delete_message=lambda *, delay_seconds, chat_id, message_id: delete_calls.append(
                    (delay_seconds, chat_id, message_id)
                )
            )
        },
    )

    assert results[0].output["forward_from_chat_id"] == -1008
    assert results[0].output["forward_message_id"] == 81
    assert fake_bot.sent_messages == [(123456, "[QA Group] Alert: urgent ticket")]
    assert fake_bot.forwarded_messages == [(123456, -1008, 81)]
    assert delete_calls == [(30, 123456, 1001), (30, 123456, 1002)]


@pytest.mark.asyncio
async def test_task_engine_notify_destination_template_can_reference_group_title(fake_bot) -> None:
    registry = build_default_registry()
    engine = TaskEngine(registry=registry, condition_evaluator=ConditionEvaluator())
    assignment = TaskAssignment(
        assignment_id="task-notify-group-title-1",
        task_key="notify_destination",
        executor_type="bot",
        conditions={"text_contains": "urgent"},
        config={"message_template": "{group_title}: {text}", "destination": "123456"},
    )

    results = await engine.process(
        [assignment],
        TaskEvent(
            name="message.received",
            group_id=-1008,
            user_id=42,
            payload={"chat_id": -1008, "group_title": "QA Group", "text": "urgent ticket", "message_id": 81, "bot": fake_bot},
        ),
        {"bot": BotTaskExecutor()},
    )

    assert results[0].output["metadata"]["source_group_title"] == "QA Group"
    assert fake_bot.sent_messages == [(123456, "QA Group: urgent ticket")]


@pytest.mark.asyncio
async def test_task_engine_can_copy_original_message_without_text(fake_bot) -> None:
    registry = build_default_registry()
    engine = TaskEngine(registry=registry, condition_evaluator=ConditionEvaluator())
    assignment = TaskAssignment(
        assignment_id="task-notify-copy-1",
        task_key="notify_destination",
        executor_type="bot",
        conditions={"text_contains": "urgent"},
        config={"destination": "ops_room", "delivery_mode": "copy"},
    )

    results = await engine.process(
        [assignment],
        TaskEvent(
            name="message.received",
            group_id=-1008,
            user_id=42,
            payload={"chat_id": -1008, "text": "urgent ticket", "message_id": 81, "bot": fake_bot},
        ),
        {"bot": BotTaskExecutor()},
    )

    assert "text" not in results[0].output
    assert results[0].output["copy_from_chat_id"] == -1008
    assert results[0].output["copy_message_id"] == 81
    assert fake_bot.sent_messages == []
    assert fake_bot.copied_messages == [("ops_room", -1008, 81)]


def test_agent_task_store_loads_automation_task_from_job_payload() -> None:
    registry = build_default_registry()
    store = AgentTaskStore(registry)
    job = AgentJob(
        id=4,
        agent_id=9,
        job_type="automation_task",
        job_payload={
            "task_key": "reply_message",
            "assignment_id": "assignment-4",
            "task_config": {"message_template": "Hello {user_id}"},
            "event": {"name": "message.received", "group_id": -1005, "user_id": 42, "payload": {"message_id": 11}},
        },
        status="pending",
    )

    binding = store.load(job)

    assert binding is not None
    assert binding.task.key == "reply_message"
    assert binding.assignment.agent_id == 9
    assert binding.assignment.assignment_id == "assignment-4"
    assert binding.event.group_id == -1005


@pytest.mark.asyncio
async def test_task_service_matches_chat_id_condition_against_telegram_chat_id(
    db_session,
    fake_bot,
) -> None:
    user = User(tg_user_id=905, username="owner5", full_name="Owner 5", language_code="en")
    db_session.add(user)
    await db_session.flush()
    group = Group(tg_group_id=-100905, title="Chat Id Group", owner_user_id=user.id, is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=user.tg_user_id, role="owner"))
    await db_session.commit()

    service = TaskService(db_session, dispatch_agent_job=lambda _: None)
    await service.save_assignment(
        actor_user_id=user.tg_user_id,
        group_id=group.id,
        task_key="reply_message",
        executor_type="bot",
        conditions={"chat_id": group.tg_group_id},
        config={"message_template": "Matched by chat id"},
    )

    await service.handle_message_event(
        group_id=group.id,
        user_id=user.tg_user_id,
        payload={"chat_id": group.tg_group_id, "text": "hello", "message_id": 34, "bot": fake_bot},
    )

    assert fake_bot.sent_messages == [(group.tg_group_id, "Matched by chat id")]


@pytest.mark.asyncio
async def test_task_service_saves_bot_assignment_and_executes_on_group_message(
    db_session,
    fake_bot,
) -> None:
    user = User(tg_user_id=901, username="owner", full_name="Owner", language_code="en")
    db_session.add(user)
    await db_session.flush()
    group = Group(tg_group_id=-100901, title="Task Group", owner_user_id=user.id, is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=user.tg_user_id, role="owner"))
    await db_session.commit()

    service = TaskService(db_session, dispatch_agent_job=lambda _: None)
    assignment = await service.save_assignment(
        actor_user_id=user.tg_user_id,
        group_id=group.id,
        task_key="reply_message",
        executor_type="bot",
        conditions={"text_contains": "price"},
        config={"message_template": "Pricing team will reply soon."},
    )

    settings_value = await service._load_assignments(group.id)
    assert settings_value[0].assignment_id == assignment["assignment_id"]
    assert assignment["group_id"] == group.id

    await service.handle_message_event(
        group_id=group.id,
        user_id=user.tg_user_id,
        payload={"text": "what is the price?", "message_id": 33, "bot": fake_bot, "contains_link": False},
    )
    assert fake_bot.sent_messages == [(
        group.id,
        "Pricing team will reply soon.",
    )]


@pytest.mark.asyncio
async def test_task_service_creates_agent_job_for_agent_assignment(db_session) -> None:
    owner = User(tg_user_id=902, username="owner2", full_name="Owner 2", language_code="en")
    db_session.add(owner)
    await db_session.flush()
    group = Group(tg_group_id=-100902, title="Agent Task Group", owner_user_id=owner.id, is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=owner.tg_user_id, role="owner"))
    agent = Agent(
        group_id=group.id,
        telegram_user_id=8100,
        external_account_id="agent-1",
        status="active",
        auth_state="active",
        session_string="session-value",
        details={},
    )
    db_session.add(agent)
    await db_session.commit()

    dispatch_mock = Mock()
    service = TaskService(db_session, dispatch_agent_job=dispatch_mock)
    await service.save_assignment(
        actor_user_id=owner.tg_user_id,
        group_id=group.id,
        task_key="reply_message",
        executor_type="agent",
        agent_id=agent.id,
        config={"message_template": "Agent reply"},
    )

    results = await service.handle_message_event(
        group_id=group.id,
        user_id=owner.tg_user_id,
        payload={"text": "hello", "message_id": 55, "bot": SimpleNamespace(), "contains_link": False},
    )

    jobs = (await db_session.execute(select(AgentJob).where(AgentJob.agent_id == agent.id))).scalars().all()
    assert len(jobs) == 1
    assert jobs[0].job_type == "automation_task"
    dispatch_mock.assert_called_once_with(jobs[0].id)
    assert results[0]["job_id"] == jobs[0].id


@pytest.mark.asyncio
async def test_task_service_rejects_agent_assignment_from_another_group(db_session) -> None:
    owner = User(tg_user_id=908, username="owner8", full_name="Owner 8", language_code="en")
    db_session.add(owner)
    await db_session.flush()
    source_group = Group(tg_group_id=-100908, title="Source Group", owner_user_id=owner.id, is_active=True)
    target_group = Group(tg_group_id=-100909, title="Target Group", owner_user_id=owner.id, is_active=True)
    db_session.add_all([source_group, target_group])
    await db_session.flush()
    db_session.add_all(
        [
            GroupAdminRole(group_id=source_group.id, user_id=owner.tg_user_id, role="owner"),
            GroupAdminRole(group_id=target_group.id, user_id=owner.tg_user_id, role="owner"),
        ]
    )
    agent = Agent(
        group_id=source_group.id,
        telegram_user_id=8104,
        external_account_id="agent-other-group",
        status="active",
        auth_state="active",
        session_string="session-other-group",
        details={},
    )
    db_session.add(agent)
    await db_session.commit()

    service = TaskService(db_session, dispatch_agent_job=lambda _: None)

    with pytest.raises(ValueError, match="Assigned agent must belong to the selected group"):
        await service.save_assignment(
            actor_user_id=owner.tg_user_id,
            group_id=target_group.id,
            task_key="reply_message",
            executor_type="agent",
            agent_id=agent.id,
            config={"message_template": "Cross-group agent reply"},
        )


@pytest.mark.asyncio
async def test_task_service_persists_lead_capture_metadata(db_session, fake_bot) -> None:
    owner = User(tg_user_id=904, username="owner4", full_name="Owner 4", language_code="en")
    db_session.add(owner)
    await db_session.flush()
    group = Group(tg_group_id=-100904, title="Lead Group", owner_user_id=owner.id, is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=owner.tg_user_id, role="owner"))
    await db_session.commit()

    service = TaskService(db_session, dispatch_agent_job=lambda _: None, dispatch_follow_up=None)
    await service.save_assignment(
        actor_user_id=owner.tg_user_id,
        group_id=group.id,
        task_key="lead_capture",
        executor_type="bot",
        conditions={"text_contains": "quote"},
        config={"ack_template": "Thanks", "lead_label": "sales", "ask_contact": True},
    )

    await service.handle_message_event(
        group_id=group.id,
        user_id=owner.tg_user_id,
        payload={"chat_id": group.tg_group_id, "text": "need a quote", "message_id": 101, "bot": fake_bot},
    )

    logs = (
        await db_session.execute(select(ModerationLog).where(ModerationLog.group_id == group.id))
    ).scalars().all()
    assert any(log.action == "lead_captured" and log.details.get("lead_label") == "sales" for log in logs)


@pytest.mark.asyncio
async def test_agent_task_runtime_dispatches_message_event_to_user_agent_executor(
    monkeypatch: pytest.MonkeyPatch,
    session_factory,
    db_session,
) -> None:
    owner = User(tg_user_id=903, username="owner3", full_name="Owner 3", language_code="en")
    db_session.add(owner)
    await db_session.flush()
    group = Group(tg_group_id=-100903, title="Runtime Group", owner_user_id=owner.id, is_active=True)
    db_session.add(group)
    await db_session.flush()
    agent = Agent(
        group_id=group.id,
        telegram_user_id=8101,
        external_account_id="agent-runtime",
        status="active",
        auth_state="active",
        session_string="session-runtime",
        details={},
    )
    db_session.add(agent)
    await db_session.flush()
    job = AgentJob(
        agent_id=agent.id,
        job_type="automation_task",
        job_payload={
            "task_key": "reply_message",
            "task_config": {"message_template": "Runtime reply"},
            "event": {"name": "message.received", "group_id": group.tg_group_id, "user_id": owner.tg_user_id, "payload": {"message_id": 99}},
        },
        status="pending",
    )
    db_session.add(job)
    await db_session.commit()

    monkeypatch.setattr("bot.agents.runtime.SessionLocal", session_factory)
    executor = SimpleNamespace(execute=AsyncMock(return_value={"ok": True}))
    runtime = AgentTaskRuntime(registry=build_default_registry(), executor=executor)

    dispatched = await runtime.dispatch_job(job.id)

    async with session_factory() as verification_session:
        stored = (await verification_session.execute(select(AgentJob).where(AgentJob.id == job.id))).scalar_one()
    assert dispatched is True
    assert stored.status == "completed"
    executor.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_agent_task_runtime_passes_telegram_chat_id_to_user_agent_executor(
    monkeypatch: pytest.MonkeyPatch,
    session_factory,
    db_session,
) -> None:
    owner = User(tg_user_id=906, username="owner6", full_name="Owner 6", language_code="en")
    db_session.add(owner)
    await db_session.flush()
    group = Group(tg_group_id=-100906, title="Runtime Chat Group", owner_user_id=owner.id, is_active=True)
    db_session.add(group)
    await db_session.flush()
    agent = Agent(
        group_id=group.id,
        telegram_user_id=8102,
        external_account_id="agent-chat",
        status="active",
        auth_state="active",
        session_string="session-chat",
        details={},
    )
    db_session.add(agent)
    await db_session.flush()
    job = AgentJob(
        agent_id=agent.id,
        job_type="automation_task",
        job_payload={
            "task_key": "reply_message",
            "task_config": {"message_template": "Runtime reply"},
            "event": {
                "name": "message.received",
                "group_id": group.id,
                "user_id": owner.tg_user_id,
                "payload": {"chat_id": group.tg_group_id, "message_id": 100},
            },
        },
        status="pending",
    )
    db_session.add(job)
    await db_session.commit()

    monkeypatch.setattr("bot.agents.runtime.SessionLocal", session_factory)
    executor = SimpleNamespace(execute=AsyncMock(return_value={"ok": True}))
    runtime = AgentTaskRuntime(registry=build_default_registry(), executor=executor)

    dispatched = await runtime.dispatch_job(job.id)

    assert dispatched is True
    executor.execute.assert_awaited_once()
    assert executor.execute.await_args.kwargs["payload"]["chat_id"] == group.tg_group_id


@pytest.mark.asyncio
async def test_execute_agent_job_marks_failed_when_agent_session_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    session_factory,
    db_session,
) -> None:
    owner = User(tg_user_id=907, username="owner7", full_name="Owner 7", language_code="en")
    db_session.add(owner)
    await db_session.flush()
    group = Group(tg_group_id=-100907, title="Worker Failure Group", owner_user_id=owner.id, is_active=True)
    db_session.add(group)
    await db_session.flush()
    agent = Agent(
        group_id=group.id,
        telegram_user_id=8103,
        external_account_id="agent-failure",
        status="active",
        auth_state="active",
        session_string="session-failure",
        details={},
    )
    db_session.add(agent)
    await db_session.flush()
    job = AgentJob(
        agent_id=agent.id,
        job_type="group_member_broadcast",
        job_payload={
            "source_group_id": group.tg_group_id,
            "message": "Promo update",
            "threshold": 1,
            "interval_seconds": 0,
        },
        status="pending",
    )
    db_session.add(job)
    await db_session.commit()

    class FailingSessionManager:
        async def get_client(self, agent_id: int):
            raise AgentSessionError("Telegram client auth is not configured")

    monkeypatch.setattr("bot.agents.worker.SessionLocal", session_factory)
    monkeypatch.setattr("bot.agents.worker.SessionManager", FailingSessionManager)

    await execute_agent_job.fn(agent.id, job.id)

    async with session_factory() as verification_session:
        stored = (await verification_session.execute(select(AgentJob).where(AgentJob.id == job.id))).scalar_one()
    assert stored.status == "failed"
    assert stored.job_payload["last_error"] == "Telegram client auth is not configured"


@pytest.mark.asyncio
async def test_group_member_broadcast_runtime_respects_threshold_and_interval() -> None:
    participants = [
        SimpleNamespace(id=8102, bot=False, deleted=False),
        SimpleNamespace(id=9001, bot=False, deleted=False),
        SimpleNamespace(id=9002, bot=True, deleted=False),
        SimpleNamespace(id=9003, bot=False, deleted=False),
        SimpleNamespace(id=9004, bot=False, deleted=False),
    ]

    class FakeClient:
        def __init__(self) -> None:
            self.sent_messages: list[tuple[int, str]] = []

        async def get_entity(self, tg_group_id):
            return SimpleNamespace(id=tg_group_id)

        async def iter_participants(self, entity):
            assert getattr(entity, "id", entity) == -100999
            for participant in participants:
                yield participant

        async def send_message(self, entity, message=None):
            self.sent_messages.append((entity, message))

    sleep = AsyncMock()
    runtime = GroupMemberBroadcastRuntime(sleep=sleep)
    agent = Agent(
        id=10,
        group_id=1,
        telegram_user_id=8102,
        external_account_id="sender-agent",
        status="active",
        auth_state="active",
        session_string="session",
        details={},
    )
    client = FakeClient()

    result = await runtime.execute(
        client=client,
        agent=agent,
        payload={
            "source_group_id": -100999,
            "message": "Promo update",
            "threshold": 2,
            "interval_seconds": 3,
        },
    )

    assert len(client.sent_messages) == 3
    assert (9001, "Promo update") in client.sent_messages
    assert (9003, "Promo update") in client.sent_messages
    assert (9004, "Promo update") in client.sent_messages
    assert result["success_count"] == 3
    assert result["failure_count"] == 0
    assert result["total_count"] == 3
    assert sleep.await_count == 2
    sleep.assert_awaited_with(3.0)


@pytest.mark.asyncio
async def test_scraper_runtime_passes_max_age_days_to_full_group_scrape(
    monkeypatch: pytest.MonkeyPatch,
    session_factory,
    db_session,
) -> None:
    owner = User(tg_user_id=908, username="owner8", full_name="Owner 8", language_code="en")
    db_session.add(owner)
    await db_session.flush()
    group = Group(tg_group_id=-100908, title="Scraper Runtime Group", owner_user_id=owner.id, is_active=True)
    db_session.add(group)
    await db_session.flush()
    agent = Agent(
        group_id=group.id,
        telegram_user_id=8104,
        external_account_id="agent-scraper-runtime",
        status="active",
        auth_state="active",
        session_string="session-scraper-runtime",
        details={},
    )
    db_session.add(agent)
    await db_session.commit()

    captured: dict[str, int | bool | None] = {}

    async def fake_scrape_full_group(self, **kwargs):
        _ = self
        captured.update(kwargs)
        return {
            "group_info": None,
            "members": {"success_count": 5, "error_count": 0, "total_scraped": 5},
            "messages": {"success_count": 8, "error_count": 0, "total_scraped": 8},
        }

    monkeypatch.setattr("bot.agents.runtime.SessionLocal", session_factory)
    monkeypatch.setattr("bot.agents.runtime.ScraperService.scrape_full_group", fake_scrape_full_group)

    runtime = ScraperRuntime()
    result = await runtime.execute(
        client=SimpleNamespace(),
        agent=agent,
        payload={
            "tg_group_id": group.tg_group_id,
            "scrape_members": True,
            "scrape_messages": True,
            "member_limit": 250,
            "message_limit": 500,
            "max_age_days": 14,
        },
        job_type="scraper_full_group",
    )

    assert result["job_type"] == "scraper_full_group"
    assert captured["agent_id"] == agent.id
    assert captured["tg_group_id"] == group.tg_group_id
    assert captured["member_limit"] == 250
    assert captured["message_limit"] == 500
    assert captured["max_age_days"] == 14
