from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.types import MessageEntity
from sqlalchemy import select

from bot.handlers.automation_notify import handle_notify_destination_approval
from bot.handlers.automation_notify import handle_notify_destination_edit_reply
from bot.handlers.automation_notify import NotifyDestinationEditableReplyFilter
from bot.db.models import Agent
from bot.services.notify_destination_approval_service import NotifyDestinationApprovalService
from bot.db.models import Group, ModerationLog


@pytest.mark.asyncio
async def test_notify_destination_approval_yes_sends_private_reply(
    db_session,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
    session_factory,
) -> None:
    monkeypatch.setattr("bot.db.session.SessionLocal", session_factory)
    group = Group(tg_group_id=-1007200, title="Notify Approval Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(
        Agent(
            id=13,
            group_id=group.id,
            telegram_user_id=9013,
            external_account_id="ops-agent",
            status="active",
            auth_state="active",
            session_string="session",
            details={"username": "ops_agent"},
        )
    )
    await db_session.commit()

    payload = await NotifyDestinationApprovalService(db_session).create_prompt(
        group_id=group.id,
        assignment_id="task-1",
        task_key="notify_destination",
        agent_id=13,
        destination=555001,
        prompt_text="Approve sending the reply?",
        private_reply_text="Private reply body.",
        target_user_id=777001,
        source_group_title="Sales Group",
        original_message_text="Need pricing info",
        source_chat_id=-1009001,
        source_message_id=87,
        bot=fake_bot,
    )

    sent_via_agent: list[tuple[int, str]] = []

    class FakeClient:
        async def disconnect(self) -> None:
            return None

    class FakeSessionManager:
        def __init__(self, session_factory=None) -> None:
            _ = session_factory

        async def get_client(self, agent_id: int):
            assert agent_id == 13
            return FakeClient()

    class FakeAgentExecutor:
        async def execute(self, *, client=None, payload=None, agent=None):
            _ = client
            _ = agent
            sent_via_agent.append((int(payload["chat_id"]), str(payload["text"])))
            return payload

    monkeypatch.setattr("bot.handlers.automation_notify.SessionManager", FakeSessionManager)
    monkeypatch.setattr("bot.handlers.automation_notify.UserAgentExecutor", FakeAgentExecutor)

    callback = SimpleNamespace(
        data=f"notify-destination:yes:{group.id}:{payload['token']}",
        bot=fake_bot,
        from_user=SimpleNamespace(id=9001, username="reviewer", full_name="Review Admin"),
        message=SimpleNamespace(delete=AsyncMock(), chat=SimpleNamespace(id=555001)),
        answer=AsyncMock(),
    )

    await handle_notify_destination_approval(callback)

    updated = await NotifyDestinationApprovalService(db_session).get_prompt(group_id=group.id, token=payload["token"])
    assert updated is not None
    assert fake_bot.sent_messages == [
        (555001, "Approve sending the reply?\n\nAgent: @ops_agent"),
        (
            555001,
            "Notification Report\n\n"
            "Status: Approved\n"
            "Send confirmed by: @reviewer\n"
            "Agent: @ops_agent\n"
            "Destination: 555001\n"
            "Source: Sales Group (message #87)\n"
            "Time: "
            f"{updated['acted_at'].replace('T', ' ')[:19]} UTC\n\n"
            "Reply sent:\n"
            "Private reply body.\n\n"
            "Original message:\n"
            "Need pricing info",
        ),
    ]
    assert sent_via_agent == [(777001, "Private reply body.")]
    assert updated["status"] == "approved"
    assert updated["acted_by_user_id"] == 9001
    assert updated["acted_by_username"] == "reviewer"
    assert updated["acted_by_name"] == "Review Admin"
    rows = (await db_session.execute(select(ModerationLog).where(ModerationLog.action == "notify_destination_confirmation"))).scalars().all()
    assert len(rows) == 1
    assert rows[0].admin_user_id == 9001
    assert rows[0].reason == "approved"
    assert rows[0].details["token"] == payload["token"]
    assert rows[0].details["confirmed_by_username"] == "reviewer"
    callback.message.delete.assert_awaited_once()
    callback.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_notify_destination_approval_no_replaces_prompt_with_report(
    db_session,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
    session_factory,
) -> None:
    monkeypatch.setattr("bot.db.session.SessionLocal", session_factory)
    group = Group(tg_group_id=-1007202, title="Notify Approval Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(
        Agent(
            id=15,
            group_id=group.id,
            telegram_user_id=9015,
            external_account_id="notify-agent",
            status="active",
            auth_state="active",
            session_string="session",
            details={"username": "notify_agent"},
        )
    )
    await db_session.commit()

    payload = await NotifyDestinationApprovalService(db_session).create_prompt(
        group_id=group.id,
        assignment_id="task-3",
        task_key="notify_destination",
        agent_id=15,
        destination=555002,
        prompt_text="Approve sending the reply?",
        private_reply_text="Private reply body.",
        target_user_id=777003,
        source_group_title="Support Group",
        original_message_text="Refund request",
        source_chat_id=-1009002,
        source_message_id=45,
        bot=fake_bot,
    )

    callback = SimpleNamespace(
        data=f"notify-destination:no:{group.id}:{payload['token']}",
        bot=fake_bot,
        from_user=SimpleNamespace(id=9004, username="decliner", full_name="Decline Admin"),
        message=SimpleNamespace(delete=AsyncMock(), chat=SimpleNamespace(id=555002)),
        answer=AsyncMock(),
    )

    await handle_notify_destination_approval(callback)

    updated = await NotifyDestinationApprovalService(db_session).get_prompt(group_id=group.id, token=payload["token"])
    assert updated is not None
    assert fake_bot.sent_messages == [
        (555002, "Approve sending the reply?\n\nAgent: @notify_agent"),
        (
            555002,
            "Notification Report\n\n"
            "Status: Declined\n"
            "Send confirmed by: @decliner\n"
            "Agent: @notify_agent\n"
            "Destination: 555002\n"
            "Source: Support Group (message #45)\n"
            "Time: "
            f"{updated['acted_at'].replace('T', ' ')[:19]} UTC\n\n"
            "Reply sent:\n"
            "Private reply body.\n\n"
            "Original message:\n"
            "Refund request",
        ),
    ]
    assert updated["status"] == "declined"
    assert updated["acted_by_user_id"] == 9004
    callback.message.delete.assert_awaited_once()
    callback.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_notify_destination_edit_reply_sends_custom_reply_and_replaces_prompt(
    db_session,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
    session_factory,
) -> None:
    monkeypatch.setattr("bot.db.session.SessionLocal", session_factory)
    group = Group(tg_group_id=-1007201, title="Notify Approval Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(
        Agent(
            id=14,
            group_id=group.id,
            telegram_user_id=9014,
            external_account_id="reply-agent",
            status="active",
            auth_state="active",
            session_string="session",
            details={"username": "reply_agent"},
        )
    )
    await db_session.commit()

    payload = await NotifyDestinationApprovalService(db_session).create_prompt(
        group_id=group.id,
        assignment_id="task-2",
        task_key="notify_destination",
        agent_id=14,
        destination=-1005001,
        prompt_text="Approve sending the reply?",
        private_reply_text="Old reply.",
        target_user_id=777002,
        source_group_title="Ops Group",
        original_message_text="Please contact me",
        source_chat_id=-1009003,
        source_message_id=52,
        bot=fake_bot,
    )
    await NotifyDestinationApprovalService(db_session).mark_prompt(
        group_id=group.id,
        token=payload["token"],
        status="editing",
        acted_by_user_id=9002,
        acted_by_username="editor",
        acted_by_name="Edit Admin",
    )

    sent_via_agent: list[tuple[int, str]] = []

    class FakeClient:
        async def disconnect(self) -> None:
            return None

    class FakeSessionManager:
        def __init__(self, session_factory=None) -> None:
            _ = session_factory

        async def get_client(self, agent_id: int):
            assert agent_id == 14
            return FakeClient()

    class FakeAgentExecutor:
        async def execute(self, *, client=None, payload=None, agent=None):
            _ = client
            _ = agent
            sent_via_agent.append((int(payload["chat_id"]), str(payload["text"])))
            return payload

    monkeypatch.setattr("bot.handlers.automation_notify.SessionManager", FakeSessionManager)
    monkeypatch.setattr("bot.handlers.automation_notify.UserAgentExecutor", FakeAgentExecutor)

    reply_to_message = SimpleNamespace(message_id=payload["prompt_message_id"], delete=AsyncMock(), chat=SimpleNamespace(id=-1005001))
    message = SimpleNamespace(
        reply_to_message=reply_to_message,
        from_user=SimpleNamespace(id=9003, username="customizer", full_name="Custom Admin"),
        chat=SimpleNamespace(id=-1005001, type="supergroup"),
        bot=fake_bot,
        text="Custom reply body",
        caption=None,
        reply=AsyncMock(),
    )

    await handle_notify_destination_edit_reply(message)

    updated = await NotifyDestinationApprovalService(db_session).get_prompt(group_id=group.id, token=payload["token"])
    assert updated is not None
    assert fake_bot.sent_messages == [
        (-1005001, "Approve sending the reply?\n\nAgent: @reply_agent"),
        (
            -1005001,
            "Notification Report\n\n"
            "Status: Approved with edited reply\n"
            "Send confirmed by: @customizer\n"
            "Agent: @reply_agent\n"
            "Destination: -1005001\n"
            "Source: Ops Group (message #52)\n"
            "Time: "
            f"{updated['acted_at'].replace('T', ' ')[:19]} UTC\n\n"
            "Reply sent:\n"
            "Custom reply body\n\n"
            "Original message:\n"
            "Please contact me",
        ),
    ]
    assert sent_via_agent == [(777002, "Custom reply body")]
    assert updated["status"] == "approved_edited"
    assert updated["private_reply_text"] == "Custom reply body"
    assert updated["acted_by_user_id"] == 9003
    reply_to_message.delete.assert_awaited_once()
    message.reply.assert_awaited_once()


@pytest.mark.asyncio
async def test_notify_destination_edit_reply_ignores_command_replies(
    db_session,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
    session_factory,
) -> None:
    monkeypatch.setattr("bot.db.session.SessionLocal", session_factory)
    group = Group(tg_group_id=-1007203, title="Notify Approval Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(
        Agent(
            id=16,
            group_id=group.id,
            telegram_user_id=9016,
            external_account_id="reply-agent-2",
            status="active",
            auth_state="active",
            session_string="session",
            details={"username": "reply_agent_2"},
        )
    )
    await db_session.commit()

    payload = await NotifyDestinationApprovalService(db_session).create_prompt(
        group_id=group.id,
        assignment_id="task-4",
        task_key="notify_destination",
        agent_id=16,
        destination=-1005002,
        prompt_text="Approve sending the reply?",
        private_reply_text="Old reply.",
        target_user_id=777004,
        source_group_title="Ops Group",
        original_message_text="Please contact me",
        source_chat_id=-1009004,
        source_message_id=53,
        bot=fake_bot,
    )
    await NotifyDestinationApprovalService(db_session).mark_prompt(
        group_id=group.id,
        token=payload["token"],
        status="editing",
        acted_by_user_id=9002,
        acted_by_username="editor",
        acted_by_name="Edit Admin",
    )

    get_client = AsyncMock()
    monkeypatch.setattr("bot.handlers.automation_notify.SessionManager", lambda session_factory=None: SimpleNamespace(get_client=get_client))

    reply_to_message = SimpleNamespace(message_id=payload["prompt_message_id"], delete=AsyncMock(), chat=SimpleNamespace(id=-1005002))
    message = SimpleNamespace(
        reply_to_message=reply_to_message,
        from_user=SimpleNamespace(id=9003, username="customizer", full_name="Custom Admin"),
        chat=SimpleNamespace(id=-1005002, type="supergroup"),
        bot=fake_bot,
        text="/ban",
        caption=None,
        entities=[MessageEntity(type="bot_command", offset=0, length=4)],
        caption_entities=[],
        reply=AsyncMock(),
    )

    await handle_notify_destination_edit_reply(message)

    updated = await NotifyDestinationApprovalService(db_session).get_prompt(group_id=group.id, token=payload["token"])
    assert updated is not None
    assert updated["status"] == "editing"
    assert get_client.await_count == 0
    assert fake_bot.sent_messages == [(-1005002, "Approve sending the reply?\n\nAgent: @reply_agent_2")]
    reply_to_message.delete.assert_not_awaited()
    message.reply.assert_not_awaited()


@pytest.mark.asyncio
async def test_notify_destination_edit_reply_ignores_plain_text_moderation_aliases(
    db_session,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
    session_factory,
) -> None:
    monkeypatch.setattr("bot.db.session.SessionLocal", session_factory)
    group = Group(tg_group_id=-1007204, title="Notify Approval Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(
        Agent(
            id=17,
            group_id=group.id,
            telegram_user_id=9017,
            external_account_id="reply-agent-3",
            status="active",
            auth_state="active",
            session_string="session",
            details={"username": "reply_agent_3"},
        )
    )
    await db_session.commit()

    payload = await NotifyDestinationApprovalService(db_session).create_prompt(
        group_id=group.id,
        assignment_id="task-5",
        task_key="notify_destination",
        agent_id=17,
        destination=-1005003,
        prompt_text="Approve sending the reply?",
        private_reply_text="Old reply.",
        target_user_id=777005,
        source_group_title="Ops Group",
        original_message_text="Please contact me",
        source_chat_id=-1009005,
        source_message_id=54,
        bot=fake_bot,
    )
    await NotifyDestinationApprovalService(db_session).mark_prompt(
        group_id=group.id,
        token=payload["token"],
        status="editing",
        acted_by_user_id=9002,
        acted_by_username="editor",
        acted_by_name="Edit Admin",
    )

    get_client = AsyncMock()
    monkeypatch.setattr("bot.handlers.automation_notify.SessionManager", lambda session_factory=None: SimpleNamespace(get_client=get_client))

    reply_to_message = SimpleNamespace(message_id=payload["prompt_message_id"], delete=AsyncMock(), chat=SimpleNamespace(id=-1005003))
    message = SimpleNamespace(
        reply_to_message=reply_to_message,
        from_user=SimpleNamespace(id=9003, username="customizer", full_name="Custom Admin"),
        chat=SimpleNamespace(id=-1005003, type="supergroup"),
        bot=fake_bot,
        text="mute",
        caption=None,
        entities=[],
        caption_entities=[],
        reply=AsyncMock(),
    )

    await handle_notify_destination_edit_reply(message)

    updated = await NotifyDestinationApprovalService(db_session).get_prompt(group_id=group.id, token=payload["token"])
    assert updated is not None
    assert updated["status"] == "editing"
    assert get_client.await_count == 0
    assert fake_bot.sent_messages == [(-1005003, "Approve sending the reply?\n\nAgent: @reply_agent_3")]
    reply_to_message.delete.assert_not_awaited()
    message.reply.assert_not_awaited()


@pytest.mark.asyncio
async def test_notify_destination_edit_filter_rejects_command_replies() -> None:
    message = SimpleNamespace(
        reply_to_message=SimpleNamespace(message_id=77),
        from_user=SimpleNamespace(id=9003),
        chat=SimpleNamespace(id=-1005002, type="supergroup"),
        text="/ban",
        caption=None,
        entities=[MessageEntity(type="bot_command", offset=0, length=4)],
        caption_entities=[],
    )

    allowed = await NotifyDestinationEditableReplyFilter()(message)

    assert allowed is False


@pytest.mark.asyncio
async def test_notify_destination_edit_filter_rejects_plain_text_moderation_aliases() -> None:
    message = SimpleNamespace(
        reply_to_message=SimpleNamespace(message_id=78),
        from_user=SimpleNamespace(id=9004),
        chat=SimpleNamespace(id=-1005003, type="supergroup"),
        text="ban",
        caption=None,
        entities=[],
        caption_entities=[],
    )

    allowed = await NotifyDestinationEditableReplyFilter()(message)

    assert allowed is False


@pytest.mark.asyncio
async def test_notify_destination_edit_filter_allows_custom_group_replies() -> None:
    message = SimpleNamespace(
        reply_to_message=SimpleNamespace(message_id=79),
        from_user=SimpleNamespace(id=9005),
        chat=SimpleNamespace(id=-1005004, type="supergroup"),
        text="Custom reply body",
        caption=None,
        entities=[],
        caption_entities=[],
    )

    allowed = await NotifyDestinationEditableReplyFilter()(message)

    assert allowed is True
