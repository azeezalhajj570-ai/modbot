"""Tests for the join request verification (access gate) flow."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace

import pytest
from aiogram.types import ChatJoinRequest, User as TGUser, Chat
from sqlalchemy import select

from bot.db.models import Group, GroupAdminRole, User as UserModel, JoinRequestApproval
from bot.handlers.join_request import on_chat_join_request
from bot.handlers.join_request_callbacks import handle_joinreq_callback
from bot.services.access_gate_service import AccessGateService
from bot.services.join_request_service import _chat_id_candidates
from bot.services.settings_service import SettingsService

import bot.handlers.join_request as join_request_module
import bot.handlers.join_request_callbacks as join_request_callbacks_module


def _set_member_status(fake_bot, chat_id: int, user_id: int, status: str) -> None:
    """Set FakeTelegramBot chat_member status for all candidate ID formats."""
    for cid in _chat_id_candidates(chat_id):
        fake_bot.chat_members[(cid, user_id)] = SimpleNamespace(status=status)


@pytest.mark.asyncio
async def test_auto_approve_when_all_groups_joined(
    db_session, fake_bot, monkeypatch,
):
    """User is already a member of all required gate groups — should auto-approve."""
    user = UserModel(tg_user_id=777, username="testuser", full_name="Test User")
    db_session.add(user)
    await db_session.flush()

    group = Group(tg_group_id=-1001001, title="Protected Group", owner_user_id=user.id)
    db_session.add(group)
    await db_session.flush()

    db_session.add(GroupAdminRole(group_id=group.id, user_id=777, role="owner"))
    await db_session.commit()

    await SettingsService(db_session).set_value(group.id, "join_request_verify", True)

    required_tg_id = -1002001
    await AccessGateService(db_session).add_required_group(group.id, required_tg_id)

    async def mock_resolve(session, tg_id):
        return group
    monkeypatch.setattr(join_request_module, "resolve_group_by_tg_id", mock_resolve)

    @asynccontextmanager
    async def mock_session_local():
        yield db_session
    monkeypatch.setattr(join_request_module, "SessionLocal", mock_session_local)

    # User is a member of the required gate group
    _set_member_status(fake_bot, required_tg_id, 777, "member")

    user_tg = TGUser(id=777, is_bot=False, first_name="Test User")
    chat = Chat(id=-1001001, type="supergroup", title="Protected Group")
    event = ChatJoinRequest(
        chat=chat,
        from_user=user_tg,
        date=datetime.utcnow(),
        user_chat_id=777,
        invite_link=None,
    )
    event._bot = fake_bot

    await on_chat_join_request(event)

    assert fake_bot.approved_join_requests == [(-1001001, 777)]

    # No pending record should exist
    stmt = select(JoinRequestApproval).where(
        JoinRequestApproval.protected_group_tg_id == -1001001,
        JoinRequestApproval.user_tg_id == 777,
    )
    result = await db_session.execute(stmt)
    approvals = result.scalars().all()
    assert len(approvals) == 0


@pytest.mark.asyncio
async def test_pending_created_when_missing_groups(
    db_session, fake_bot, monkeypatch,
):
    """User is NOT in a required gate group — create pending record + notify user."""
    user = UserModel(tg_user_id=777, username="testuser", full_name="Test User")
    db_session.add(user)
    await db_session.flush()

    group = Group(tg_group_id=-1001001, title="Protected Group", owner_user_id=user.id)
    db_session.add(group)
    await db_session.flush()

    db_session.add(GroupAdminRole(group_id=group.id, user_id=777, role="owner"))
    await db_session.commit()

    await SettingsService(db_session).set_value(group.id, "join_request_verify", True)

    required_tg_id = -1002001
    await AccessGateService(db_session).add_required_group(group.id, required_tg_id)

    async def mock_resolve(session, tg_id):
        return group
    monkeypatch.setattr(join_request_module, "resolve_group_by_tg_id", mock_resolve)

    @asynccontextmanager
    async def mock_session_local():
        yield db_session
    monkeypatch.setattr(join_request_module, "SessionLocal", mock_session_local)

    # User is NOT in the required gate group
    _set_member_status(fake_bot, required_tg_id, 777, "left")

    # Required gate group info for the verification keyboard
    fake_bot.chats[required_tg_id] = SimpleNamespace(
        id=required_tg_id, title="Gate Group", username="gate_group",
    )

    user_tg = TGUser(id=777, is_bot=False, first_name="Test User")
    chat = Chat(id=-1001001, type="supergroup", title="Protected Group")
    event = ChatJoinRequest(
        chat=chat,
        from_user=user_tg,
        date=datetime.utcnow(),
        user_chat_id=777,
        invite_link=None,
    )
    event._bot = fake_bot

    await on_chat_join_request(event)

    # Should NOT have approved
    assert fake_bot.approved_join_requests == []

    # A pending record should exist
    stmt = select(JoinRequestApproval).where(
        JoinRequestApproval.protected_group_tg_id == -1001001,
        JoinRequestApproval.user_tg_id == 777,
    )
    result = await db_session.execute(stmt)
    approvals = result.scalars().all()
    assert len(approvals) == 1
    approval = approvals[0]
    assert approval.status == "pending"
    assert approval.required_group_tg_ids == str(required_tg_id)
    assert approval.verified_group_tg_ids == ""

    # User should have been sent a verification message
    sent_texts = [t for _, t in fake_bot.sent_messages]
    assert any("verification" in t.lower() and "join" in t.lower() for t in sent_texts)


@pytest.mark.asyncio
async def test_refresh_detects_user_joined_gate_group(
    db_session, fake_bot, monkeypatch,
):
    """After pending, user joins gate group — refresh callback detects it."""
    user = UserModel(tg_user_id=777, username="testuser", full_name="Test User")
    db_session.add(user)
    await db_session.flush()

    group = Group(tg_group_id=-1001001, title="Protected Group", owner_user_id=user.id)
    db_session.add(group)
    await db_session.flush()

    db_session.add(GroupAdminRole(group_id=group.id, user_id=777, role="owner"))
    await db_session.commit()

    await SettingsService(db_session).set_value(group.id, "join_request_verify", True)

    required_tg_id = -1002001
    await AccessGateService(db_session).add_required_group(group.id, required_tg_id)

    async def mock_resolve(session, tg_id):
        return group
    monkeypatch.setattr(join_request_module, "resolve_group_by_tg_id", mock_resolve)

    @asynccontextmanager
    async def mock_session_local():
        yield db_session
    monkeypatch.setattr(join_request_module, "SessionLocal", mock_session_local)
    monkeypatch.setattr(join_request_callbacks_module, "SessionLocal", mock_session_local)

    _set_member_status(fake_bot, required_tg_id, 777, "left")
    fake_bot.chats[required_tg_id] = SimpleNamespace(
        id=required_tg_id, title="Gate Group", username="gate_group",
    )

    user_tg = TGUser(id=777, is_bot=False, first_name="Test User")
    chat = Chat(id=-1001001, type="supergroup", title="Protected Group")
    event = ChatJoinRequest(
        chat=chat,
        from_user=user_tg,
        date=datetime.utcnow(),
        user_chat_id=777,
        invite_link=None,
    )
    event._bot = fake_bot

    await on_chat_join_request(event)

    # Get the pending approval record
    stmt = select(JoinRequestApproval).where(
        JoinRequestApproval.protected_group_tg_id == -1001001,
        JoinRequestApproval.user_tg_id == 777,
    )
    result = await db_session.execute(stmt)
    approval = result.scalars().one()

    # User now joins the gate group
    _set_member_status(fake_bot, required_tg_id, 777, "member")

    # Simulate "Check Membership" callback
    from tests.conftest import FakeCallbackQuery, FakeMessage

    msg = FakeMessage(
        chat_id=777, chat_type="private", user_id=777, text="check",
        bot=fake_bot,
    )
    cb = FakeCallbackQuery(
        data=f"joinreq_refresh:{approval.id}",
        from_user_id=777,
        message=msg,
    )
    await handle_joinreq_callback(cb)

    # Should have edited the message to say all groups joined
    assert len(msg.log.edits) >= 1
    edit_texts = [e["text"] for e in msg.log.edits]
    assert any("joined all required groups" in t.lower() for t in edit_texts)

    # Approval should now be marked with verified groups
    await db_session.refresh(approval)
    assert str(required_tg_id) in (approval.verified_group_tg_ids or "")
