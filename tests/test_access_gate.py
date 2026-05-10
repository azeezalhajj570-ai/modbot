from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import select

from bot.core.event_bus import EventBus
from bot.db.models import Group, GroupAccessRequirement, ModerationLog
from bot.handlers.moderation.events import on_group_message
from bot.services.access_gate_service import AccessGateService
from bot.utils.i18n import t


@pytest.mark.asyncio
async def test_access_gate_service_crud(db_session, seeded_group) -> None:
    service = AccessGateService(db_session)

    await service.add_required_group(seeded_group["group_id"], -100222)
    await service.add_required_group(seeded_group["group_id"], -100333)

    required = sorted(await service.list_required_group_tg_ids(seeded_group["group_id"]))
    assert required == [-100333, -100222]

    await service.remove_required_group(seeded_group["group_id"], -100333)
    required = await service.list_required_group_tg_ids(seeded_group["group_id"])
    assert required == [-100222]

    await service.clear_required_groups(seeded_group["group_id"])
    assert await service.list_required_group_tg_ids(seeded_group["group_id"]) == []


class _GateBot:
    def __init__(self, member_status: str, is_member: bool | None = None) -> None:
        self.member_status = member_status
        self.is_member = is_member
        self.member_chat_ids: list[int] = []
        self.chats: dict[int, SimpleNamespace] = {}
        self.invite_links: dict[int, str] = {}

    async def get_chat_member(self, chat_id: int, _user_id: int) -> SimpleNamespace:
        self.member_chat_ids.append(chat_id)
        payload = {"status": self.member_status}
        if self.is_member is not None:
            payload["is_member"] = self.is_member
        return SimpleNamespace(**payload)

    async def get_chat(self, chat_id: int) -> SimpleNamespace:
        if chat_id in self.chats:
            return self.chats[chat_id]
        raise RuntimeError("chat not found")

    async def export_chat_invite_link(self, chat_id: int) -> str:
        if chat_id in self.invite_links:
            return self.invite_links[chat_id]
        raise RuntimeError("invite link unavailable")


@pytest.mark.asyncio
async def test_access_gate_deletes_message_when_user_not_member(
    patch_db_dependencies,
    patch_moderation_events_session,
    db_session,
    seeded_group,
    fake_message_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    required_group = Group(tg_group_id=-1007788, title="Required", is_active=True)
    db_session.add(required_group)
    await db_session.flush()
    db_session.add(
        GroupAccessRequirement(
            protected_group_id=seeded_group["group_id"],
            required_group_tg_id=required_group.tg_group_id,
        )
    )
    await db_session.commit()

    monkeypatch.setattr("bot.handlers.moderation.events.run_spam_analysis.send", Mock())

    message = fake_message_factory(
        chat_id=seeded_group["tg_group_id"],
        chat_type="group",
        user_id=9999,
        text="hello",
        message_id=51,
        bot=_GateBot(member_status="left"),
    )
    message.bot.chats[required_group.tg_group_id] = SimpleNamespace(username="requiredgroup")

    await on_group_message(message, EventBus())

    assert len(message.log.deletes) == 1
    assert message.log.answers[-1]["text"] == (
        f"{t('access_gate_blocked', 'ar')}\n"
        f"{t('access_gate_required_groups', 'ar', groups='Required')}"
    )
    buttons = message.log.answers[-1]["reply_markup"].inline_keyboard
    assert buttons[0][0].text == "Required"
    assert buttons[0][0].url == "https://t.me/requiredgroup"
    log = (
        await db_session.execute(
            select(ModerationLog).where(
                ModerationLog.group_id == seeded_group["group_id"],
                ModerationLog.action == "delete_not_in_required_groups",
            )
        )
    ).scalar_one()
    assert log.target_user_id == 9999


@pytest.mark.asyncio
async def test_access_gate_allows_member_and_continues_pipeline(
    patch_db_dependencies,
    patch_moderation_events_session,
    db_session,
    seeded_group,
    fake_message_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    required_group = Group(tg_group_id=-1008899, title="Required", is_active=True)
    db_session.add(required_group)
    await db_session.flush()
    db_session.add(
        GroupAccessRequirement(
            protected_group_id=seeded_group["group_id"],
            required_group_tg_id=required_group.tg_group_id,
        )
    )
    await db_session.commit()

    send_mock = Mock()
    monkeypatch.setattr("bot.handlers.moderation.events.run_spam_analysis.send", send_mock)

    message = fake_message_factory(
        chat_id=seeded_group["tg_group_id"],
        chat_type="group",
        user_id=9999,
        text="hello",
        message_id=52,
        bot=_GateBot(member_status="member"),
    )

    await on_group_message(message, EventBus())

    assert message.log.deletes == []
    send_mock.assert_called_once_with(seeded_group["tg_group_id"], 52, 9999, "hello", "ar")


@pytest.mark.asyncio
async def test_access_gate_allows_owner_status(
    patch_db_dependencies,
    patch_moderation_events_session,
    db_session,
    seeded_group,
    fake_message_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    required_group = Group(tg_group_id=-1009900, title="Required", is_active=True)
    db_session.add(required_group)
    await db_session.flush()
    db_session.add(
        GroupAccessRequirement(
            protected_group_id=seeded_group["group_id"],
            required_group_tg_id=required_group.tg_group_id,
        )
    )
    await db_session.commit()

    send_mock = Mock()
    monkeypatch.setattr("bot.handlers.moderation.events.run_spam_analysis.send", send_mock)

    message = fake_message_factory(
        chat_id=seeded_group["tg_group_id"],
        chat_type="group",
        user_id=9999,
        text="hello",
        message_id=53,
        bot=_GateBot(member_status="owner"),
    )

    await on_group_message(message, EventBus())

    assert message.log.deletes == []
    send_mock.assert_called_once_with(seeded_group["tg_group_id"], 53, 9999, "hello", "ar")


@pytest.mark.asyncio
async def test_access_gate_restricted_non_member_gets_deleted(
    patch_db_dependencies,
    patch_moderation_events_session,
    db_session,
    seeded_group,
    fake_message_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    required_group = Group(tg_group_id=-1009911, title="Required", is_active=True)
    db_session.add(required_group)
    await db_session.flush()
    db_session.add(
        GroupAccessRequirement(
            protected_group_id=seeded_group["group_id"],
            required_group_tg_id=required_group.tg_group_id,
        )
    )
    await db_session.commit()

    monkeypatch.setattr("bot.handlers.moderation.events.run_spam_analysis.send", Mock())

    message = fake_message_factory(
        chat_id=seeded_group["tg_group_id"],
        chat_type="group",
        user_id=9999,
        text="hello",
        message_id=54,
        bot=_GateBot(member_status="restricted", is_member=False),
    )

    await on_group_message(message, EventBus())

    assert len(message.log.deletes) == 1


@pytest.mark.asyncio
async def test_access_gate_deletes_non_text_message_for_non_member(
    patch_db_dependencies,
    patch_moderation_events_session,
    db_session,
    seeded_group,
    fake_message_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    required_group = Group(tg_group_id=-1009922, title="Required", is_active=True)
    db_session.add(required_group)
    await db_session.flush()
    db_session.add(
        GroupAccessRequirement(
            protected_group_id=seeded_group["group_id"],
            required_group_tg_id=required_group.tg_group_id,
        )
    )
    await db_session.commit()

    send_mock = Mock()
    monkeypatch.setattr("bot.handlers.moderation.events.run_spam_analysis.send", send_mock)

    message = fake_message_factory(
        chat_id=seeded_group["tg_group_id"],
        chat_type="group",
        user_id=9999,
        text="",
        message_id=55,
        bot=_GateBot(member_status="left"),
    )
    message.text = None
    message.caption = None

    await on_group_message(message, EventBus())

    assert len(message.log.deletes) == 1
    send_mock.assert_not_called()


@pytest.mark.asyncio
async def test_access_gate_matches_legacy_group_id_after_supergroup_upgrade(
    patch_db_dependencies,
    patch_moderation_events_session,
    db_session,
    fake_message_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protected_group = Group(tg_group_id=-222333, title="Legacy Protected", is_active=True)
    db_session.add(protected_group)
    required_group = Group(tg_group_id=-100444555, title="Required", is_active=True)
    db_session.add(required_group)
    await db_session.flush()
    db_session.add(
        GroupAccessRequirement(
            protected_group_id=protected_group.id,
            required_group_tg_id=required_group.tg_group_id,
        )
    )
    await db_session.commit()

    monkeypatch.setattr("bot.handlers.moderation.events.run_spam_analysis.send", Mock())

    upgraded_chat_id = -100222333
    message = fake_message_factory(
        chat_id=upgraded_chat_id,
        chat_type="supergroup",
        user_id=9999,
        text="hello",
        message_id=56,
        bot=_GateBot(member_status="left"),
    )

    await on_group_message(message, EventBus())

    assert len(message.log.deletes) == 1
    log = (
        await db_session.execute(
            select(ModerationLog).where(
                ModerationLog.group_id == protected_group.id,
                ModerationLog.action == "delete_not_in_required_groups",
            )
        )
    ).scalar_one()
    assert log.target_user_id == 9999


@pytest.mark.asyncio
async def test_access_gate_checks_supergroup_variant_for_required_group_membership(
    patch_db_dependencies,
    patch_moderation_events_session,
    db_session,
    seeded_group,
    fake_message_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    required_group = Group(tg_group_id=-889900, title="Legacy Required", is_active=True)
    db_session.add(required_group)
    await db_session.flush()
    db_session.add(
        GroupAccessRequirement(
            protected_group_id=seeded_group["group_id"],
            required_group_tg_id=required_group.tg_group_id,
        )
    )
    await db_session.commit()

    send_mock = Mock()
    monkeypatch.setattr("bot.handlers.moderation.events.run_spam_analysis.send", send_mock)

    class _VariantGateBot(_GateBot):
        async def get_chat_member(self, chat_id: int, user_id: int) -> SimpleNamespace:
            self.member_chat_ids.append(chat_id)
            if chat_id == -100889900:
                return await super().get_chat_member(chat_id, user_id)
            raise RuntimeError("legacy id no longer valid")

    bot = _VariantGateBot(member_status="member")
    message = fake_message_factory(
        chat_id=seeded_group["tg_group_id"],
        chat_type="supergroup",
        user_id=9999,
        text="hello",
        message_id=57,
        bot=bot,
    )

    await on_group_message(message, EventBus())

    assert message.log.deletes == []
    assert -889900 in bot.member_chat_ids
    assert -100889900 in bot.member_chat_ids
    send_mock.assert_called_once_with(seeded_group["tg_group_id"], 57, 9999, "hello", "ar")


@pytest.mark.asyncio
async def test_access_gate_requires_membership_in_all_configured_groups(
    patch_db_dependencies,
    patch_moderation_events_session,
    db_session,
    seeded_group,
    fake_message_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    required_group_one = Group(tg_group_id=-100555001, title="Required One", is_active=True)
    required_group_two = Group(tg_group_id=-100555002, title="Required Two", is_active=True)
    db_session.add(required_group_one)
    db_session.add(required_group_two)
    await db_session.flush()
    db_session.add(
        GroupAccessRequirement(
            protected_group_id=seeded_group["group_id"],
            required_group_tg_id=required_group_one.tg_group_id,
        )
    )
    db_session.add(
        GroupAccessRequirement(
            protected_group_id=seeded_group["group_id"],
            required_group_tg_id=required_group_two.tg_group_id,
        )
    )
    await db_session.commit()

    monkeypatch.setattr("bot.handlers.moderation.events.run_spam_analysis.send", Mock())

    class _PartialGateBot(_GateBot):
        async def get_chat_member(self, chat_id: int, user_id: int) -> SimpleNamespace:
            self.member_chat_ids.append(chat_id)
            if chat_id == required_group_one.tg_group_id:
                return SimpleNamespace(status="member")
            return SimpleNamespace(status="left")

    bot = _PartialGateBot(member_status="left")
    bot.chats[required_group_two.tg_group_id] = SimpleNamespace(username="requiredtwo")
    message = fake_message_factory(
        chat_id=seeded_group["tg_group_id"],
        chat_type="supergroup",
        user_id=9999,
        text="hello",
        message_id=58,
        bot=bot,
    )

    await on_group_message(message, EventBus())

    assert len(message.log.deletes) == 1
    assert message.log.answers[-1]["text"] == (
        f"{t('access_gate_blocked', 'ar')}\n"
        f"{t('access_gate_required_groups', 'ar', groups='Required Two')}"
    )
    log = (
        await db_session.execute(
            select(ModerationLog).where(
                ModerationLog.group_id == seeded_group["group_id"],
                ModerationLog.action == "delete_not_in_required_groups",
            )
        )
    ).scalar_one()
    assert sorted(log.details["required_groups"]) == sorted(
        [required_group_one.tg_group_id, required_group_two.tg_group_id]
    )
    assert log.details["missing_required_groups"] == [required_group_two.tg_group_id]
