from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from bot.db.models import ModerationLog
from bot.handlers.commands.moderation import (
    ban_handler,
    mute_handler,
    moderation_reply_alias_handler,
    purge_handler,
    unban_handler,
    unmute_handler,
)
from bot.utils.i18n import t


def _reply_message(user_id: int) -> SimpleNamespace:
    return SimpleNamespace(from_user=SimpleNamespace(id=user_id))


@pytest.mark.asyncio
async def test_ban_command_bans_replied_user(
    patch_db_dependencies,
    db_session,
    seeded_group,
    fake_message_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scheduled_deletes: list[dict[str, int]] = []
    monkeypatch.setattr(
        "bot.handlers.commands.moderation.schedule_bot_message_delete",
        lambda **kwargs: scheduled_deletes.append(kwargs),
    )
    fake_bot.chat_members[(seeded_group["tg_group_id"], seeded_group["user_id"])] = SimpleNamespace(status="administrator")
    message = fake_message_factory(
        chat_id=seeded_group["tg_group_id"],
        chat_type="supergroup",
        user_id=seeded_group["user_id"],
        text="/ban",
        bot=fake_bot,
    )
    message.reply_to_message = _reply_message(9999)

    await ban_handler(message)

    assert fake_bot.banned_members == [(seeded_group["tg_group_id"], 9999)]
    assert message.log.answers[-1]["text"] == t("ban_done", "ar")
    logs = (
        await db_session.execute(select(ModerationLog).where(ModerationLog.group_id == seeded_group["group_id"]))
    ).scalars().all()
    assert any(log.action == "ban_user" and log.target_user_id == 9999 for log in logs)
    assert scheduled_deletes == [{"delay_seconds": 60, "chat_id": seeded_group["tg_group_id"], "message_id": message.message_id}]


@pytest.mark.asyncio
async def test_unban_command_unbans_replied_user(
    patch_db_dependencies,
    seeded_group,
    fake_message_factory,
    fake_bot,
) -> None:
    fake_bot.chat_members[(seeded_group["tg_group_id"], seeded_group["user_id"])] = SimpleNamespace(status="administrator")
    message = fake_message_factory(
        chat_id=seeded_group["tg_group_id"],
        chat_type="supergroup",
        user_id=seeded_group["user_id"],
        text="/unban",
        bot=fake_bot,
    )
    message.reply_to_message = _reply_message(9999)

    await unban_handler(message)

    assert fake_bot.unbanned_members == [(seeded_group["tg_group_id"], 9999)]
    assert message.log.answers[-1]["text"] == t("unban_done", "ar")


@pytest.mark.asyncio
async def test_mute_and_unmute_commands_apply_restrictions(
    patch_db_dependencies,
    seeded_group,
    fake_message_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scheduled_deletes: list[dict[str, int]] = []
    monkeypatch.setattr(
        "bot.handlers.commands.moderation.schedule_bot_message_delete",
        lambda **kwargs: scheduled_deletes.append(kwargs),
    )
    fake_bot.chat_members[(seeded_group["tg_group_id"], seeded_group["user_id"])] = SimpleNamespace(status="administrator")

    mute_message = fake_message_factory(
        chat_id=seeded_group["tg_group_id"],
        chat_type="supergroup",
        user_id=seeded_group["user_id"],
        text="/mute",
        bot=fake_bot,
    )
    mute_message.reply_to_message = _reply_message(9999)
    await mute_handler(mute_message)

    unmute_message = fake_message_factory(
        chat_id=seeded_group["tg_group_id"],
        chat_type="supergroup",
        user_id=seeded_group["user_id"],
        text="/unmute",
        bot=fake_bot,
    )
    unmute_message.reply_to_message = _reply_message(9999)
    await unmute_handler(unmute_message)

    assert fake_bot.muted_members == [(seeded_group["tg_group_id"], 9999)]
    assert len(fake_bot.unmuted_members) == 1
    assert unmute_message.log.answers[-1]["text"] == t("unmute_done", "ar")
    assert scheduled_deletes == [{"delay_seconds": 60, "chat_id": seeded_group["tg_group_id"], "message_id": mute_message.message_id}]


@pytest.mark.asyncio
async def test_purge_command_deletes_requested_count(
    patch_db_dependencies,
    seeded_group,
    fake_message_factory,
    fake_bot,
) -> None:
    fake_bot.chat_members[(seeded_group["tg_group_id"], seeded_group["user_id"])] = SimpleNamespace(status="administrator")
    message = fake_message_factory(
        chat_id=seeded_group["tg_group_id"],
        chat_type="supergroup",
        user_id=seeded_group["user_id"],
        text="/purge 3",
        message_id=50,
        bot=fake_bot,
    )

    await purge_handler(message)

    assert fake_bot.deleted_messages == [
        (seeded_group["tg_group_id"], 50),
        (seeded_group["tg_group_id"], 49),
        (seeded_group["tg_group_id"], 48),
        (seeded_group["tg_group_id"], 47),
    ]
    assert message.log.answers[-1]["text"] == t("purge_done", "ar", count=4)


@pytest.mark.asyncio
async def test_non_admin_cannot_use_moderation_commands(
    patch_db_dependencies,
    db_session,
    seeded_group,
    fake_message_factory,
    fake_bot,
) -> None:
    fake_bot.chat_members[(seeded_group["tg_group_id"], seeded_group["user_id"])] = SimpleNamespace(status="member")
    message = fake_message_factory(
        chat_id=seeded_group["tg_group_id"],
        chat_type="supergroup",
        user_id=seeded_group["user_id"],
        text="/ban",
        bot=fake_bot,
    )
    message.reply_to_message = _reply_message(9999)

    await ban_handler(message)

    assert fake_bot.banned_members == []
    assert fake_bot.muted_members == []
    assert message.log.answers[-1]["text"] == t("registergroup_admin_only", "ar")
    logs = (
        await db_session.execute(select(ModerationLog).where(ModerationLog.group_id == seeded_group["group_id"]))
    ).scalars().all()
    assert any(log.action == "unauthorized_moderation_command" and log.target_user_id == seeded_group["user_id"] for log in logs)


@pytest.mark.asyncio
async def test_non_admin_is_muted_after_three_unauthorized_moderation_attempts(
    patch_db_dependencies,
    db_session,
    seeded_group,
    fake_message_factory,
    fake_bot,
) -> None:
    fake_bot.chat_members[(seeded_group["tg_group_id"], seeded_group["user_id"])] = SimpleNamespace(status="member")

    for _ in range(3):
        message = fake_message_factory(
            chat_id=seeded_group["tg_group_id"],
            chat_type="supergroup",
            user_id=seeded_group["user_id"],
            text="/ban",
            bot=fake_bot,
        )
        message.reply_to_message = _reply_message(9999)
        await ban_handler(message)

    assert fake_bot.muted_members == [(seeded_group["tg_group_id"], seeded_group["user_id"])]
    assert fake_bot.banned_members == []
    logs = (
        await db_session.execute(select(ModerationLog).where(ModerationLog.group_id == seeded_group["group_id"]))
    ).scalars().all()
    assert sum(1 for log in logs if log.action == "unauthorized_moderation_command") == 3
    assert any(log.action == "mute_unauthorized_command_user" and log.target_user_id == seeded_group["user_id"] for log in logs)


@pytest.mark.asyncio
async def test_non_admin_is_banned_after_five_unauthorized_moderation_attempts(
    patch_db_dependencies,
    db_session,
    seeded_group,
    fake_message_factory,
    fake_bot,
) -> None:
    fake_bot.chat_members[(seeded_group["tg_group_id"], seeded_group["user_id"])] = SimpleNamespace(status="member")

    for _ in range(5):
        message = fake_message_factory(
            chat_id=seeded_group["tg_group_id"],
            chat_type="supergroup",
            user_id=seeded_group["user_id"],
            text="/mute",
            bot=fake_bot,
        )
        message.reply_to_message = _reply_message(9999)
        await mute_handler(message)

    assert fake_bot.muted_members == [(seeded_group["tg_group_id"], seeded_group["user_id"])]
    assert fake_bot.banned_members == [(seeded_group["tg_group_id"], seeded_group["user_id"])]
    logs = (
        await db_session.execute(select(ModerationLog).where(ModerationLog.group_id == seeded_group["group_id"]))
    ).scalars().all()
    assert sum(1 for log in logs if log.action == "unauthorized_moderation_command") == 5
    assert any(log.action == "ban_unauthorized_command_user" and log.target_user_id == seeded_group["user_id"] for log in logs)


@pytest.mark.asyncio
async def test_ban_command_requires_reply(
    patch_db_dependencies,
    seeded_group,
    fake_message_factory,
    fake_bot,
) -> None:
    fake_bot.chat_members[(seeded_group["tg_group_id"], seeded_group["user_id"])] = SimpleNamespace(status="administrator")
    message = fake_message_factory(
        chat_id=seeded_group["tg_group_id"],
        chat_type="supergroup",
        user_id=seeded_group["user_id"],
        text="/ban",
        bot=fake_bot,
    )

    await ban_handler(message)

    assert fake_bot.banned_members == []
    assert message.log.answers[-1]["text"] == t("moderation_reply_required", "ar")


@pytest.mark.asyncio
async def test_plain_text_ban_reply_alias_bans_user(
    patch_db_dependencies,
    seeded_group,
    fake_message_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("bot.handlers.commands.moderation.schedule_bot_message_delete", lambda **_: None)
    fake_bot.chat_members[(seeded_group["tg_group_id"], seeded_group["user_id"])] = SimpleNamespace(status="administrator")
    message = fake_message_factory(
        chat_id=seeded_group["tg_group_id"],
        chat_type="supergroup",
        user_id=seeded_group["user_id"],
        text="ban",
        bot=fake_bot,
    )
    message.reply_to_message = _reply_message(9999)

    await moderation_reply_alias_handler(message)

    assert fake_bot.banned_members == [(seeded_group["tg_group_id"], 9999)]


@pytest.mark.asyncio
async def test_plain_text_arabic_mute_reply_alias_mutes_user(
    patch_db_dependencies,
    seeded_group,
    fake_message_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("bot.handlers.commands.moderation.schedule_bot_message_delete", lambda **_: None)
    fake_bot.chat_members[(seeded_group["tg_group_id"], seeded_group["user_id"])] = SimpleNamespace(status="administrator")
    message = fake_message_factory(
        chat_id=seeded_group["tg_group_id"],
        chat_type="supergroup",
        user_id=seeded_group["user_id"],
        text="كتم",
        bot=fake_bot,
    )
    message.reply_to_message = _reply_message(9999)

    await moderation_reply_alias_handler(message)

    assert fake_bot.muted_members == [(seeded_group["tg_group_id"], 9999)]
