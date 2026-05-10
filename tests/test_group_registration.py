from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from bot.db.models import Group, GroupAdminRole
from bot.handlers.commands.register_group import register_group
from bot.handlers import fallback


@pytest.mark.asyncio
async def test_register_group_syncs_all_current_admins(
    patch_db_dependencies,
    db_session,
    fake_bot,
    fake_message_factory,
) -> None:
    fake_bot.chat_members[(-100555, 1001)] = SimpleNamespace(status="administrator")
    fake_bot.chat_administrators[-100555] = [
        SimpleNamespace(
            status="creator",
            user=SimpleNamespace(
                id=2002,
                is_bot=False,
                username="owner",
                full_name="Owner User",
                language_code="en",
            ),
        ),
        SimpleNamespace(
            status="administrator",
            user=SimpleNamespace(
                id=1001,
                is_bot=False,
                username="adder",
                full_name="Adder User",
                language_code="en",
            ),
        ),
    ]
    message = fake_message_factory(
        chat_id=-100555,
        chat_type="supergroup",
        user_id=1001,
        text="/registergroup",
    )
    message.chat.title = "Fresh Group"

    await register_group(message)

    group = (await db_session.execute(select(Group).where(Group.tg_group_id == -100555))).scalar_one()
    roles = (
        await db_session.execute(
            select(GroupAdminRole.user_id, GroupAdminRole.role).where(GroupAdminRole.group_id == group.id)
        )
    ).all()

    assert group.title == "Fresh Group"
    assert group.is_active is True
    assert sorted(roles) == [(1001, "admin"), (2002, "owner")]


@pytest.mark.asyncio
async def test_my_chat_member_refresh_registers_group_for_current_admins(
    db_session,
    fake_bot,
    session_factory,
    monkeypatch,
) -> None:
    monkeypatch.setattr(fallback, "SessionLocal", session_factory)
    fake_bot.chat_administrators[-100777] = [
        SimpleNamespace(
            status="creator",
            user=SimpleNamespace(
                id=3003,
                is_bot=False,
                username="owner",
                full_name="Group Owner",
                language_code="en",
            ),
        ),
        SimpleNamespace(
            status="administrator",
            user=SimpleNamespace(
                id=4004,
                is_bot=False,
                username="admin",
                full_name="Group Admin",
                language_code="en",
            ),
        ),
    ]
    event = SimpleNamespace(
        chat=SimpleNamespace(id=-100777, type="supergroup", title="Refreshable Group"),
        old_chat_member=SimpleNamespace(status="left"),
        new_chat_member=SimpleNamespace(status="member"),
        from_user=SimpleNamespace(
            id=4004,
            username="admin",
            full_name="Group Admin",
            language_code="en",
        ),
        bot=fake_bot,
    )

    await fallback.my_chat_member_fallback(event)

    group = (await db_session.execute(select(Group).where(Group.tg_group_id == -100777))).scalar_one()
    roles = (
        await db_session.execute(
            select(GroupAdminRole.user_id, GroupAdminRole.role).where(GroupAdminRole.group_id == group.id)
        )
    ).all()

    assert group.title == "Refreshable Group"
    assert group.is_active is True
    assert sorted(roles) == [(3003, "owner"), (4004, "admin")]


@pytest.mark.asyncio
async def test_my_chat_member_refresh_registers_channel_for_current_admins(
    db_session,
    fake_bot,
    session_factory,
    monkeypatch,
) -> None:
    monkeypatch.setattr(fallback, "SessionLocal", session_factory)
    fake_bot.chat_administrators[-100888] = [
        SimpleNamespace(
            status="creator",
            user=SimpleNamespace(
                id=5005,
                is_bot=False,
                username="channel_owner",
                full_name="Channel Owner",
                language_code="en",
            ),
        ),
        SimpleNamespace(
            status="administrator",
            user=SimpleNamespace(
                id=6006,
                is_bot=False,
                username="channel_admin",
                full_name="Channel Admin",
                language_code="en",
            ),
        ),
    ]
    event = SimpleNamespace(
        chat=SimpleNamespace(id=-100888, type="channel", title="Managed Channel"),
        old_chat_member=SimpleNamespace(status="left"),
        new_chat_member=SimpleNamespace(status="administrator"),
        from_user=SimpleNamespace(
            id=6006,
            username="channel_admin",
            full_name="Channel Admin",
            language_code="en",
        ),
        bot=fake_bot,
    )

    await fallback.my_chat_member_fallback(event)

    group = (await db_session.execute(select(Group).where(Group.tg_group_id == -100888))).scalar_one()
    roles = (
        await db_session.execute(
            select(GroupAdminRole.user_id, GroupAdminRole.role).where(GroupAdminRole.group_id == group.id)
        )
    ).all()

    assert group.title == "Managed Channel"
    assert group.is_active is True
    assert sorted(roles) == [(5005, "owner"), (6006, "admin")]
