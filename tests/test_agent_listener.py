from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select

from bot.agents.exceptions import AgentSessionRevokedError
from bot.agents.listener import AgentListenerManager
from bot.db.models import Agent, AgentJob, Group, GroupAdminRole, GroupMember, ModerationLog, User
from bot.services.task_service import TaskService


@pytest.mark.asyncio
async def test_agent_listener_dispatches_messages_for_selected_agent_group(
    db_session,
    session_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = User(tg_user_id=9201, username="owner9201", full_name="Owner 9201", language_code="en")
    db_session.add(owner)
    await db_session.flush()
    group = Group(tg_group_id=-1009201, title="Listener Group", owner_user_id=owner.id, is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=owner.tg_user_id, role="owner"))
    agent = Agent(
        group_id=group.id,
        telegram_user_id=99001,
        external_account_id="listener-agent",
        status="active",
        auth_state="active",
        session_string="session-listener",
        details={},
    )
    db_session.add(agent)
    await db_session.commit()

    await TaskService(db_session, dispatch_agent_job=lambda _job_id: None).save_assignment(
        actor_user_id=owner.tg_user_id,
        group_id=group.id,
        task_key="reply_message",
        executor_type="agent",
        agent_id=agent.id,
        conditions={"text_contains": "support"},
        config={"message_template": "Agent reply"},
    )

    dispatch_mock = Mock()
    seen_logs: list[dict[str, object]] = []
    monkeypatch.setattr("bot.agents.listener.SessionLocal", session_factory)
    monkeypatch.setattr("bot.agents.listener.dispatch_agent_job", dispatch_mock)
    monkeypatch.setattr("bot.agents.listener.logger.info", lambda event_name, **kwargs: seen_logs.append({"event_name": event_name, **kwargs}))

    manager = AgentListenerManager(bot=fake_bot, session_factory=session_factory)
    handled = await manager._dispatch_agent_message(
        agent.id,
        chat_id=group.tg_group_id,
        group_title=group.title,
        text="support needed",
        message_id=501,
        user_id=owner.tg_user_id,
        first_name="Owner",
        full_name="Owner 9201",
        username="owner9201",
    )

    async with session_factory() as verification_session:
        jobs = (await verification_session.execute(select(AgentJob).where(AgentJob.agent_id == agent.id))).scalars().all()
    assert handled is True
    assert len(jobs) == 1
    assert jobs[0].job_type == "automation_task"
    assert jobs[0].job_payload["event"]["payload"]["chat_id"] == group.tg_group_id
    dispatch_mock.assert_called_once_with(jobs[0].id)
    assert not any(item["event_name"] == "agent_listener_message_received" for item in seen_logs)


@pytest.mark.asyncio
async def test_agent_listener_ignores_messages_for_unselected_group(
    db_session,
    session_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = User(tg_user_id=9202, username="owner9202", full_name="Owner 9202", language_code="en")
    db_session.add(owner)
    await db_session.flush()
    selected_group = Group(tg_group_id=-1009202, title="Selected Group", owner_user_id=owner.id, is_active=True)
    other_group = Group(tg_group_id=-1009203, title="Other Group", owner_user_id=owner.id, is_active=True)
    db_session.add_all([selected_group, other_group])
    await db_session.flush()
    db_session.add_all(
        [
            GroupAdminRole(group_id=selected_group.id, user_id=owner.tg_user_id, role="owner"),
            GroupAdminRole(group_id=other_group.id, user_id=owner.tg_user_id, role="owner"),
        ]
    )
    agent = Agent(
        group_id=selected_group.id,
        telegram_user_id=99002,
        external_account_id="listener-agent-2",
        status="active",
        auth_state="active",
        session_string="session-listener-2",
        details={},
    )
    db_session.add(agent)
    await db_session.commit()

    await TaskService(db_session, dispatch_agent_job=lambda _job_id: None).save_assignment(
        actor_user_id=owner.tg_user_id,
        group_id=selected_group.id,
        task_key="reply_message",
        executor_type="agent",
        agent_id=agent.id,
        conditions={"text_contains": "support"},
        config={"message_template": "Agent reply"},
    )

    dispatch_mock = Mock()
    seen_logs: list[dict[str, object]] = []
    monkeypatch.setattr("bot.agents.listener.SessionLocal", session_factory)
    monkeypatch.setattr("bot.agents.listener.dispatch_agent_job", dispatch_mock)
    monkeypatch.setattr("bot.agents.listener.logger.info", lambda event_name, **kwargs: seen_logs.append({"event_name": event_name, **kwargs}))

    manager = AgentListenerManager(bot=fake_bot, session_factory=session_factory)
    handled = await manager._dispatch_agent_message(
        agent.id,
        chat_id=other_group.tg_group_id,
        group_title=other_group.title,
        text="support needed",
        message_id=502,
        user_id=owner.tg_user_id,
        first_name="Owner",
        full_name="Owner 9202",
        username="owner9202",
    )

    async with session_factory() as verification_session:
        jobs = (await verification_session.execute(select(AgentJob).where(AgentJob.agent_id == agent.id))).scalars().all()
    assert handled is False
    assert jobs == []
    dispatch_mock.assert_not_called()
    assert not any(item["event_name"] == "agent_listener_message_received" for item in seen_logs)


@pytest.mark.asyncio
async def test_agent_listener_does_not_log_incoming_messages_by_default(
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_logs: list[dict[str, object]] = []
    monkeypatch.setattr("bot.agents.listener.logger.info", lambda event_name, **kwargs: seen_logs.append({"event_name": event_name, **kwargs}))

    manager = AgentListenerManager(bot=fake_bot)

    class FakeEvent:
        chat_id = 92055
        sender_id = 77001
        raw_text = "hello from pm"
        message = type("Message", (), {"id": 901})()

        async def get_chat(self):
            return type("Chat", (), {"title": ""})()

        async def get_sender(self):
            return type("Sender", (), {"first_name": "Qu", "last_name": "", "username": "user77001"})()

    dispatch_mock = AsyncMock()
    monkeypatch.setattr(manager, "_dispatch_agent_message", dispatch_mock)

    await manager._handle_telethon_message(13, FakeEvent())

    assert dispatch_mock.await_count == 0
    assert seen_logs == []


@pytest.mark.asyncio
async def test_agent_listener_can_log_incoming_messages_when_enabled(
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_logs: list[dict[str, object]] = []
    monkeypatch.setattr("bot.agents.listener.logger.info", lambda event_name, **kwargs: seen_logs.append({"event_name": event_name, **kwargs}))

    manager = AgentListenerManager(bot=fake_bot, log_message_events=True)

    class FakeEvent:
        chat_id = 92055
        sender_id = 77001
        raw_text = "hello from pm"
        message = type("Message", (), {"id": 901})()

        async def get_chat(self):
            return type("Chat", (), {"title": ""})()

        async def get_sender(self):
            return type("Sender", (), {"first_name": "Qu", "last_name": "", "username": "user77001"})()

    dispatch_mock = AsyncMock()
    monkeypatch.setattr(manager, "_dispatch_agent_message", dispatch_mock)

    await manager._handle_telethon_message(13, FakeEvent())

    assert dispatch_mock.await_count == 0
    assert seen_logs == [
        {
            "event_name": "agent_listener_message_seen",
            "agent_id": 13,
            "chat_id": 92055,
            "user_id": 77001,
            "message_id": 901,
            "text": "hello from pm",
            "group_title": "",
            "username": "user77001",
            "first_name": "Qu",
            "full_name": "Qu",
            "is_group": False,
        }
    ]


@pytest.mark.asyncio
async def test_agent_listener_stops_retrying_when_session_is_revoked(
    db_session,
    session_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = User(tg_user_id=9204, username="owner9204", full_name="Owner 9204", language_code="en")
    db_session.add(owner)
    await db_session.flush()
    group = Group(tg_group_id=-1009204, title="Revoked Session Group", owner_user_id=owner.id, is_active=True)
    db_session.add(group)
    await db_session.flush()
    agent = Agent(
        group_id=group.id,
        telegram_user_id=99004,
        external_account_id="listener-agent-4",
        status="active",
        auth_state="active",
        session_string="session-listener-4",
        details={},
    )
    db_session.add(agent)
    await db_session.commit()

    class FakeSessionManager:
        def __init__(self) -> None:
            self.get_client_calls = 0
            self.mark_failed_calls = 0

        async def get_client(self, agent_id: int):
            self.get_client_calls += 1
            raise AgentSessionRevokedError("Agent session is no longer authorized")

        async def mark_failed(self, agent_id: int) -> None:
            self.mark_failed_calls += 1
            async with session_factory() as session:
                stored = (await session.execute(select(Agent).where(Agent.id == agent_id))).scalar_one()
                stored.status = "failed"
                stored.auth_state = "failed"
                await session.commit()

    fake_session_manager = FakeSessionManager()
    sleep = AsyncMock()
    exception_logs: list[dict[str, object]] = []
    warning_logs: list[dict[str, object]] = []
    monkeypatch.setattr("bot.agents.listener.logger.exception", lambda event_name, **kwargs: exception_logs.append({"event_name": event_name, **kwargs}))
    monkeypatch.setattr("bot.agents.listener.logger.warning", lambda event_name, **kwargs: warning_logs.append({"event_name": event_name, **kwargs}))

    manager = AgentListenerManager(
        bot=fake_bot,
        session_factory=session_factory,
        session_manager=fake_session_manager,
        sleep=sleep,
    )

    await manager._run_agent_listener(agent.id)

    async with session_factory() as verification_session:
        stored = (await verification_session.execute(select(Agent).where(Agent.id == agent.id))).scalar_one()

    assert fake_session_manager.get_client_calls == 1
    assert fake_session_manager.mark_failed_calls == 1
    assert sleep.await_count == 0
    assert stored.status == "failed"
    assert stored.auth_state == "failed"
    assert any(item["event_name"] == "agent_listener_failed" for item in exception_logs)
    assert any(item["event_name"] == "agent_listener_stopped_terminal_error" for item in warning_logs)


@pytest.mark.asyncio
async def test_agent_listener_persists_any_seen_group_message(
    db_session,
    session_factory,
    fake_bot,
) -> None:
    owner = User(tg_user_id=9205, username="owner9205", full_name="Owner 9205", language_code="en")
    db_session.add(owner)
    await db_session.flush()
    home_group = Group(tg_group_id=-1009205, title="Home Group", owner_user_id=owner.id, is_active=True)
    db_session.add(home_group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=home_group.id, user_id=owner.tg_user_id, role="owner"))
    agent = Agent(
        group_id=home_group.id,
        telegram_user_id=99005,
        linked_by_user_id=owner.tg_user_id,
        external_account_id="listener-agent-5",
        status="active",
        auth_state="active",
        session_string="session-listener-5",
        details={},
    )
    db_session.add(agent)
    await db_session.commit()

    manager = AgentListenerManager(bot=fake_bot, session_factory=session_factory)

    class FakeEvent:
        chat_id = -1005550001
        sender_id = 77005
        raw_text = "hello from remote group"
        message = type("Message", (), {"id": 905})()

        async def get_chat(self):
            return type("Chat", (), {"title": "Remote Listener Group"})()

        async def get_sender(self):
            return type("Sender", (), {"first_name": "Remote", "last_name": "User", "username": "remote77005"})()

    await manager._handle_telethon_message(agent.id, FakeEvent())

    async with session_factory() as verification_session:
        persisted_group = (await verification_session.execute(select(Group).where(Group.tg_group_id == -1005550001))).scalar_one()
        persisted_member = (
            await verification_session.execute(
                select(GroupMember).where(
                    GroupMember.group_id == persisted_group.id,
                    GroupMember.tg_user_id == 77005,
                )
            )
        ).scalar_one()
        stored_log = (
            await verification_session.execute(
                select(ModerationLog).where(
                    ModerationLog.group_id == persisted_group.id,
                    ModerationLog.action == "agent_message_seen",
                )
            )
        ).scalar_one()

    assert persisted_group.title == "Remote Listener Group"
    assert persisted_member.username == "remote77005"
    assert persisted_member.full_name == "Remote User"
    assert persisted_member.source == "agent_message_seen"
    assert stored_log.target_user_id == 77005
    assert stored_log.admin_user_id == 99005
    assert stored_log.reason == "hello from remote group"
    assert stored_log.details["agent_id"] == agent.id
    assert stored_log.details["message_id"] == 905
    assert stored_log.details["username"] == "remote77005"


@pytest.mark.asyncio
async def test_agent_listener_dispatches_remote_group_binding_stored_on_home_group(
    db_session,
    session_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = User(tg_user_id=9206, username="owner9206", full_name="Owner 9206", language_code="en")
    db_session.add(owner)
    await db_session.flush()
    home_group = Group(tg_group_id=-1009206, title="Home Listener Group", owner_user_id=owner.id, is_active=True)
    remote_group = Group(tg_group_id=-1009207, title="Remote Listener Group", owner_user_id=owner.id, is_active=True)
    db_session.add_all([home_group, remote_group])
    await db_session.flush()
    db_session.add_all(
        [
            GroupAdminRole(group_id=home_group.id, user_id=owner.tg_user_id, role="owner"),
            GroupAdminRole(group_id=remote_group.id, user_id=owner.tg_user_id, role="owner"),
        ]
    )
    agent = Agent(
        group_id=home_group.id,
        telegram_user_id=99006,
        linked_by_user_id=owner.tg_user_id,
        external_account_id="listener-agent-6",
        status="active",
        auth_state="active",
        session_string="session-listener-6",
        details={},
    )
    db_session.add(agent)
    await db_session.commit()

    async def fake_list_managed_member_groups(self, *, actor_user_id: int, agent_id: int):
        assert actor_user_id == owner.tg_user_id
        assert agent_id == agent.id
        return [{"tg_group_id": remote_group.tg_group_id, "title": remote_group.title, "id": remote_group.id}]

    monkeypatch.setattr("bot.agents.service.AgentService.list_managed_member_groups", fake_list_managed_member_groups)
    await TaskService(db_session, dispatch_agent_job=lambda _job_id: None).save_assignment(
        actor_user_id=owner.tg_user_id,
        group_id=home_group.id,
        task_key="reply_message",
        executor_type="agent",
        agent_id=agent.id,
        conditions={"text_contains": "support"},
        config={"message_template": "Agent reply"},
        group_ids=[remote_group.id],
        group_tg_ids=[remote_group.tg_group_id],
        group_titles=[remote_group.title],
    )

    dispatch_mock = Mock()
    monkeypatch.setattr("bot.agents.listener.dispatch_agent_job", dispatch_mock)
    manager = AgentListenerManager(bot=fake_bot, session_factory=session_factory)
    handled = await manager._dispatch_agent_message(
        agent.id,
        chat_id=remote_group.tg_group_id,
        group_title=remote_group.title,
        text="support needed",
        message_id=506,
        user_id=owner.tg_user_id,
        first_name="Owner",
        full_name="Owner 9206",
        username="owner9206",
    )

    async with session_factory() as verification_session:
        jobs = (await verification_session.execute(select(AgentJob).where(AgentJob.agent_id == agent.id))).scalars().all()

    assert handled is True
    assert len(jobs) == 1
    assert jobs[0].job_payload["event"]["group_id"] == home_group.id
    assert jobs[0].job_payload["event"]["payload"]["chat_id"] == remote_group.tg_group_id
    dispatch_mock.assert_called_once_with(jobs[0].id)
