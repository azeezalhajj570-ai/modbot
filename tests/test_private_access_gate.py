from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.db.models import Group, GroupAccessRequirement, PrivateAccessRequirement
from bot.handlers.commands.start import start_handler
from bot.handlers.fallback import private_fallback
from bot.utils.i18n import t


@pytest.mark.asyncio
async def test_private_start_blocked_until_user_joins_required_groups(
    patch_db_dependencies,
    db_session,
    fake_message_factory,
    fake_bot,
    fsm_context_factory,
) -> None:
    required_group = Group(tg_group_id=-1003001, title="Required Group", is_active=True)
    db_session.add(required_group)
    db_session.add(PrivateAccessRequirement(required_group_tg_id=required_group.tg_group_id))
    await db_session.commit()

    fake_bot.chats[required_group.tg_group_id] = SimpleNamespace(username="requiredgroup")
    fake_bot.chat_members[(required_group.tg_group_id, 2222)] = SimpleNamespace(status="left")
    fake_bot.chat_members[(-3001, 2222)] = SimpleNamespace(status="left")
    message = fake_message_factory(
        chat_id=7001,
        chat_type="private",
        user_id=2222,
        text="/start",
        bot=fake_bot,
    )

    state = fsm_context_factory(user_id=2222, chat_id=7001)
    await start_handler(message, state)

    assert len(message.log.answers) == 1
    assert message.log.answers[0]["text"] == (
        f"{t('private_access_gate_blocked', 'ar', member='Test User')}\n"
        f"{t('access_gate_required_groups', 'ar', groups='Required Group')}"
    )
    buttons = message.log.answers[0]["reply_markup"].inline_keyboard
    assert buttons[0][0].url == "https://t.me/requiredgroup"


@pytest.mark.asyncio
async def test_private_start_uses_invite_link_when_group_has_no_username(
    patch_db_dependencies,
    db_session,
    fake_message_factory,
    fake_bot,
    fsm_context_factory,
) -> None:
    required_group = Group(tg_group_id=-1003010, title="Invite Only", is_active=True)
    db_session.add(required_group)
    db_session.add(PrivateAccessRequirement(required_group_tg_id=required_group.tg_group_id))
    await db_session.commit()

    fake_bot.invite_links[required_group.tg_group_id] = "https://t.me/+inviteonly"
    fake_bot.chat_members[(required_group.tg_group_id, 2222)] = SimpleNamespace(status="left")
    fake_bot.chat_members[(-3010, 2222)] = SimpleNamespace(status="left")
    message = fake_message_factory(
        chat_id=7001,
        chat_type="private",
        user_id=2222,
        text="/start",
        bot=fake_bot,
    )

    state = fsm_context_factory(user_id=2222, chat_id=7001)
    await start_handler(message, state)

    assert len(message.log.answers) == 1
    buttons = message.log.answers[0]["reply_markup"].inline_keyboard
    assert buttons[0][0].text == "Invite Only"
    assert buttons[0][0].url == "https://t.me/+inviteonly"


@pytest.mark.asyncio
async def test_private_fallback_allows_member_of_required_groups(
    patch_db_dependencies,
    db_session,
    fake_message_factory,
    fake_bot,
) -> None:
    required_group = Group(tg_group_id=-1003002, title="Required Group", is_active=True)
    db_session.add(required_group)
    db_session.add(PrivateAccessRequirement(required_group_tg_id=required_group.tg_group_id))
    await db_session.commit()

    fake_bot.chat_members[(required_group.tg_group_id, 2222)] = SimpleNamespace(status="member")
    message = fake_message_factory(
        chat_id=7001,
        chat_type="private",
        user_id=2222,
        text="hello",
        bot=fake_bot,
    )

    await private_fallback(message)

    assert len(message.log.answers) == 1
    assert message.log.answers[0]["text"] == t("main_menu", "ar")


@pytest.mark.asyncio
async def test_private_start_ignores_group_access_gate_requirements(
    patch_db_dependencies,
    db_session,
    fake_message_factory,
    fake_bot,
    fsm_context_factory,
) -> None:
    protected_group = Group(tg_group_id=-1002003, title="Protected", is_active=True)
    required_group = Group(tg_group_id=-1003003, title="Moderation Gate Only", is_active=True)
    db_session.add_all([protected_group, required_group])
    await db_session.flush()
    db_session.add(
        GroupAccessRequirement(
            protected_group_id=protected_group.id,
            required_group_tg_id=required_group.tg_group_id,
        )
    )
    await db_session.commit()

    fake_bot.chat_members[(required_group.tg_group_id, 2222)] = SimpleNamespace(status="left")
    message = fake_message_factory(
        chat_id=7001,
        chat_type="private",
        user_id=2222,
        text="/start",
        bot=fake_bot,
    )

    state = fsm_context_factory(user_id=2222, chat_id=7001)
    await start_handler(message, state)

    assert len(message.log.answers) == 2
    assert message.log.answers[0]["text"] == t("main_menu", "ar")
    assert message.log.answers[1]["text"] == t("subscription_mandate_prompt", "ar")
