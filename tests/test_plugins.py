from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any

import pytest
from aiogram import Dispatcher
from sqlalchemy import select

from bot.core.event_bus import Event, EventBus
from bot.core.plugin_manager import PluginManager
from bot.db.models import Group, ModerationLog, PluginEnabled
from bot.services.moderation_notice_service import build_rule_notice
from bot.services.settings_service import SettingsService


class _DeleteFailsBot:
    def __init__(self) -> None:
        self.deleted_messages: list[tuple[int, int]] = []

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        raise RuntimeError(f"delete failed for {chat_id}:{message_id}")


@pytest.mark.asyncio
async def test_plugin_discovery_load_unload_reload(patch_db_dependencies) -> None:
    manager = PluginManager()
    dispatcher = Dispatcher()
    bus = EventBus()

    discovered = manager.discover()
    assert "bot.plugins.anti_links.plugin" in discovered
    assert "bot.plugins.semantic_assistant.plugin" in discovered

    await manager.load_plugin("bot.plugins.anti_links.plugin", dispatcher, bus)
    assert len(manager.loaded_plugins()) == 1

    await manager.reload_plugin("bot.plugins.anti_links.plugin", dispatcher, bus)
    assert len(manager.loaded_plugins()) == 1

    await manager.unload_plugin("bot.plugins.anti_links.plugin", dispatcher, bus)
    assert len(manager.loaded_plugins()) == 0


@pytest.mark.asyncio
async def test_enable_disable_for_group_persists(patch_db_dependencies, seeded_group, db_session) -> None:
    manager = PluginManager()
    await manager.enable_for_group(db_session, seeded_group["group_id"], "anti_links")
    await manager.disable_for_group(db_session, seeded_group["group_id"], "anti_links")

    row = (
        await db_session.execute(
            select(ModerationLog.id).where(ModerationLog.group_id == seeded_group["group_id"])
        )
    ).scalar_one_or_none()
    assert row is None


@pytest.mark.asyncio
async def test_anti_links_plugin_triggers_moderation_action(
    patch_db_dependencies,
    seeded_group,
    db_session,
    fake_bot,
) -> None:
    manager = PluginManager()
    dispatcher = Dispatcher()
    bus = EventBus()
    await manager.load_all(dispatcher, bus)

    await bus.publish(
        Event(
            name="MessageReceived",
            group_id=seeded_group["tg_group_id"],
            user_id=4444,
            payload={"text": "visit https://spam.example", "message_id": 77, "bot": fake_bot},
        )
    )

    logs = (
        await db_session.execute(
            select(ModerationLog).where(ModerationLog.group_id == seeded_group["group_id"])
        )
    ).scalars().all()
    assert any(log.action == "delete_link" for log in logs)
    assert fake_bot.deleted_messages == [(seeded_group["tg_group_id"], 77)]
    assert fake_bot.sent_messages == [
        (seeded_group["tg_group_id"], build_rule_notice("ar", "anti_links"))
    ]


@pytest.mark.asyncio
async def test_anti_links_respects_group_setting_disable(
    patch_db_dependencies,
    seeded_group,
    db_session,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = PluginManager()
    dispatcher = Dispatcher()
    bus = EventBus()
    await manager.load_all(dispatcher, bus)

    await SettingsService(db_session).set_value(seeded_group["group_id"], "anti_links", False)
    log_events: list[tuple[str, dict[str, Any]]] = []

    from bot.plugins.anti_links import plugin as anti_links_plugin

    monkeypatch.setattr(
        anti_links_plugin.logger,
        "info",
        lambda event_name, **kwargs: log_events.append((event_name, kwargs)),
    )

    await bus.publish(
        Event(
            name="MessageReceived",
            group_id=seeded_group["tg_group_id"],
            user_id=4444,
            payload={"text": "https://example.com", "message_id": 88, "bot": fake_bot},
        )
    )

    stored_logs = (
        await db_session.execute(
            select(ModerationLog).where(ModerationLog.group_id == seeded_group["group_id"])
        )
    ).scalars().all()
    assert not any(log.details.get("message_id") == 88 for log in stored_logs)
    assert ("anti_links_message_received", {
        "group_tg_id": seeded_group["tg_group_id"],
        "user_id": 4444,
        "message_id": 88,
        "contains_link": False,
        "has_text": True,
        "text": "https://example.com",
    }) in log_events
    assert ("anti_links_skip_disabled", {
        "group_id": seeded_group["group_id"],
        "group_tg_id": seeded_group["tg_group_id"],
        "user_id": 4444,
        "message_id": 88,
        "contains_link": False,
        "anti_links_enabled": False,
    }) in log_events


@pytest.mark.asyncio
async def test_anti_links_skips_group_admin_messages(
    patch_db_dependencies,
    seeded_group,
    db_session,
    fake_bot,
) -> None:
    manager = PluginManager()
    dispatcher = Dispatcher()
    bus = EventBus()
    await manager.load_all(dispatcher, bus)
    fake_bot.chat_members[(seeded_group["tg_group_id"], 4444)] = SimpleNamespace(status="administrator")

    await bus.publish(
        Event(
            name="MessageReceived",
            group_id=seeded_group["tg_group_id"],
            user_id=4444,
            payload={"text": "https://example.com", "message_id": 881, "bot": fake_bot},
        )
    )

    stored_logs = (
        await db_session.execute(
            select(ModerationLog).where(ModerationLog.group_id == seeded_group["group_id"])
        )
    ).scalars().all()
    assert fake_bot.deleted_messages == []
    assert fake_bot.sent_messages == []
    assert not any(log.details.get("message_id") == 881 for log in stored_logs)


@pytest.mark.asyncio
async def test_anti_links_plugin_deletes_text_link_entities(
    patch_db_dependencies,
    patch_moderation_events_session,
    seeded_group,
    db_session,
    fake_message_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = PluginManager()
    dispatcher = Dispatcher()
    bus = EventBus()
    await manager.load_all(dispatcher, bus)

    def send_mock(*_args, **_kwargs) -> None:
        return None
    monkeypatch.setattr("bot.handlers.moderation.events.run_spam_analysis.send", send_mock)

    message = fake_message_factory(
        chat_id=seeded_group["tg_group_id"],
        chat_type="supergroup",
        user_id=4444,
        text="tap here",
        message_id=89,
        bot=fake_bot,
        entities=[SimpleNamespace(type="text_link", url="https://spam.example")],
    )

    from bot.handlers.moderation.events import on_group_message

    await on_group_message(message, bus)

    logs = (
        await db_session.execute(
            select(ModerationLog).where(ModerationLog.group_id == seeded_group["group_id"])
        )
    ).scalars().all()
    assert any(log.action == "delete_link" and log.details.get("message_id") == 89 for log in logs)
    assert fake_bot.deleted_messages == [(seeded_group["tg_group_id"], 89)]
    assert fake_bot.sent_messages == [
        (seeded_group["tg_group_id"], build_rule_notice("ar", "anti_links"))
    ]


@pytest.mark.asyncio
async def test_anti_links_plugin_matches_legacy_group_variant(
    patch_db_dependencies,
    db_session,
    fake_bot,
) -> None:
    legacy_group = Group(tg_group_id=-222333, title="Legacy Gate", is_active=True)
    db_session.add(legacy_group)
    await db_session.flush()
    await db_session.commit()

    manager = PluginManager()
    dispatcher = Dispatcher()
    bus = EventBus()
    await manager.load_all(dispatcher, bus)

    await bus.publish(
        Event(
            name="MessageReceived",
            group_id=-100222333,
            user_id=4444,
            payload={"text": "visit https://spam.example", "message_id": 90, "bot": fake_bot, "contains_link": True},
        )
    )

    logs = (
        await db_session.execute(
            select(ModerationLog).where(ModerationLog.group_id == legacy_group.id)
        )
    ).scalars().all()
    assert any(log.action == "delete_link" and log.details.get("message_id") == 90 for log in logs)
    assert fake_bot.deleted_messages == [(-100222333, 90)]
    assert fake_bot.sent_messages == [
        (-100222333, build_rule_notice("ar", "anti_links"))
    ]


@pytest.mark.asyncio
async def test_anti_links_plugin_handles_link_entities_without_text(
    patch_db_dependencies,
    patch_moderation_events_session,
    seeded_group,
    db_session,
    fake_message_factory,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = PluginManager()
    dispatcher = Dispatcher()
    bus = EventBus()
    await manager.load_all(dispatcher, bus)

    def send_mock(*_args, **_kwargs) -> None:
        return None
    monkeypatch.setattr("bot.handlers.moderation.events.run_spam_analysis.send", send_mock)

    message = fake_message_factory(
        chat_id=seeded_group["tg_group_id"],
        chat_type="supergroup",
        user_id=4444,
        text="",
        message_id=91,
        bot=fake_bot,
        entities=[SimpleNamespace(type="url")],
    )
    message.text = None
    message.caption = None

    from bot.handlers.moderation.events import on_group_message

    await on_group_message(message, bus)

    logs = (
        await db_session.execute(
            select(ModerationLog).where(ModerationLog.group_id == seeded_group["group_id"])
        )
    ).scalars().all()
    assert any(log.action == "delete_link" and log.details.get("message_id") == 91 for log in logs)
    assert fake_bot.deleted_messages == [(seeded_group["tg_group_id"], 91)]
    assert fake_bot.sent_messages == [
        (seeded_group["tg_group_id"], build_rule_notice("ar", "anti_links"))
    ]


@pytest.mark.asyncio
async def test_anti_links_logs_delete_failure_reason(
    patch_db_dependencies,
    seeded_group,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = PluginManager()
    dispatcher = Dispatcher()
    bus = EventBus()
    await manager.load_all(dispatcher, bus)

    bot = _DeleteFailsBot()
    log_events: list[tuple[str, dict[str, Any]]] = []

    from bot.plugins.anti_links import plugin as anti_links_plugin

    monkeypatch.setattr(
        anti_links_plugin.logger,
        "warning",
        lambda event_name, **kwargs: log_events.append((event_name, kwargs)),
    )

    await bus.publish(
        Event(
            name="MessageReceived",
            group_id=seeded_group["tg_group_id"],
            user_id=4444,
            payload={"text": "visit https://spam.example", "message_id": 91, "bot": bot},
        )
    )

    stored_logs = (
        await db_session.execute(
            select(ModerationLog).where(ModerationLog.group_id == seeded_group["group_id"])
        )
    ).scalars().all()
    assert not any(log.details.get("message_id") == 91 for log in stored_logs)
    assert ("anti_links_delete_failed", {
        "group_id": seeded_group["group_id"],
        "group_tg_id": seeded_group["tg_group_id"],
        "user_id": 4444,
        "message_id": 91,
        "contains_link": False,
        "error": f"delete failed for {seeded_group['tg_group_id']}:91",
    }) in log_events


@pytest.mark.asyncio
async def test_semantic_assistant_plugin_replies_when_enabled(
    patch_db_dependencies,
    seeded_group,
    db_session,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = PluginManager()
    dispatcher = Dispatcher()
    bus = EventBus()
    await manager.load_all(dispatcher, bus)

    db_session.add(
        PluginEnabled(
            group_id=seeded_group["group_id"],
            plugin_name="semantic_assistant",
            enabled=True,
            config={},
        )
    )
    await SettingsService(db_session).set_value(
        seeded_group["group_id"],
        "semantic_assistant_reply_prefix",
        "مساعد",
    )
    await db_session.commit()

    semantic_assistant_plugin = importlib.import_module("bot.plugins.semantic_assistant.plugin")

    class _FakeSemanticService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def search(self, query: str, **kwargs: Any) -> SimpleNamespace | None:
            assert query == "مرحبا"
            assert kwargs["top_k"] == 3
            return SimpleNamespace(text="اهلا بك", url="https://example.com/faq")

    monkeypatch.setattr(semantic_assistant_plugin, "SemanticSearchService", _FakeSemanticService)
    monkeypatch.setattr(
        semantic_assistant_plugin,
        "get_settings",
        lambda: SimpleNamespace(
            semantic_search_url="https://semantic.example.com/search",
            semantic_search_path="/search",
            semantic_search_timeout=5.0,
        ),
    )

    await bus.publish(
        Event(
            name="MessageReceived",
            group_id=seeded_group["tg_group_id"],
            user_id=4444,
            payload={"text": "مرحبا", "message_id": 93, "bot": fake_bot},
        )
    )

    assert fake_bot.sent_messages == [
        (seeded_group["tg_group_id"], "مساعد\nاهلا بك\nhttps://example.com/faq")
    ]


@pytest.mark.asyncio
async def test_semantic_assistant_plugin_skips_when_not_enabled(
    patch_db_dependencies,
    seeded_group,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = PluginManager()
    dispatcher = Dispatcher()
    bus = EventBus()
    await manager.load_all(dispatcher, bus)

    semantic_assistant_plugin = importlib.import_module("bot.plugins.semantic_assistant.plugin")

    class _FailIfCalledSemanticService:
        def __init__(self, *_args, **_kwargs) -> None:
            raise AssertionError("semantic service should not be called while plugin is disabled")

    monkeypatch.setattr(semantic_assistant_plugin, "SemanticSearchService", _FailIfCalledSemanticService)
    monkeypatch.setattr(
        semantic_assistant_plugin,
        "get_settings",
        lambda: SimpleNamespace(
            semantic_search_url="https://semantic.example.com/search",
            semantic_search_path="/search",
            semantic_search_timeout=5.0,
        ),
    )

    await bus.publish(
        Event(
            name="MessageReceived",
            group_id=seeded_group["tg_group_id"],
            user_id=4444,
            payload={"text": "مرحبا", "message_id": 94, "bot": fake_bot},
        )
    )

    assert fake_bot.sent_messages == []
