from __future__ import annotations

from datetime import datetime
import pytest
from typing import Any
from types import SimpleNamespace
from aiogram.types import MenuButtonCommands, MenuButtonWebApp
from bot.config import get_settings
from bot.keyboards.reply.menus import (
    groups_keyboard,
    main_menu_keyboard,
    task_delete_confirm_keyboard,
    task_delete_keyboard,
    task_agent_keyboard,
    task_executor_keyboard,
    task_group_keyboard,
    tasks_menu_keyboard,
)
from bot.services.task_service import TaskService
from bot.utils.pagination import paginate

from sqlalchemy import select

from bot.db.models import Agent, Group, GroupAccessRequirement, GroupAdminRole, SubscriptionRequest, SubscriptionStatus
from bot.handlers.commands.dashboard import dashboard_handler, help_handler, language_handler, scraper_handler, settings_handler
from bot.handlers.commands.start import start_handler
from bot.handlers.menu import reply_settings
from bot.handlers.menu.settings import menu_moderation, menu_settings
from bot.handlers.menu.reply_settings import settings_entrypoint
from bot.handlers.menu.states import SettingsFlow
from bot.agents.auth import AgentTelegramAuthResult, AgentTelegramAuthSession
from bot.utils.i18n import t


class FakeTelegramAgentAuthService:
    async def start_login(self, *, phone_number: str) -> AgentTelegramAuthSession:
        return AgentTelegramAuthSession(phone_number=phone_number, session_string="session:pending", phone_code_hash="hash-1")

    async def verify_code(
        self,
        *,
        phone_number: str,
        code: str,
        phone_code_hash: str,
        session_string: str,
    ) -> AgentTelegramAuthResult:
        assert phone_number == "+15550000001"
        assert code == "12345"
        assert phone_code_hash == "hash-1"
        assert session_string == "session:pending"
        return AgentTelegramAuthResult(
            telegram_user_id=50001,
            phone_number=phone_number,
            username="salesbot",
            full_name="Sales Bot",
            session_string="session:active",
        )

    async def verify_password(self, *, password: str, session_string: str) -> AgentTelegramAuthResult:
        raise AssertionError("2FA should not be requested in this test")


@pytest.mark.asyncio
async def test_private_main_menu_buttons_follow_saved_english_language(
    patch_db_dependencies,
    db_session,
    seeded_group,
    fake_message_factory,
    fsm_context_factory,
    plugin_manager,
) -> None:
    db_session.add(
        SubscriptionRequest(
            tg_user_id=seeded_group["user_id"],
            username="tester",
            full_name="Test User",
            status=SubscriptionStatus.APPROVED.value,
        )
    )
    from bot.db.models import User as UserModel
    user = (await db_session.execute(select(UserModel).where(UserModel.tg_user_id == seeded_group["user_id"]))).scalar_one()
    assert user is not None
    user.language_code = "ar"
    await db_session.commit()
    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])

    open_language = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text=f"🌐 {t('language', 'ar')}",
    )
    await settings_entrypoint(open_language, state, plugin_manager)
    assert open_language.log.answers[-1]["text"] == t("choose_language", "ar")

    switch_to_english = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="🇬🇧 English",
    )
    await settings_entrypoint(switch_to_english, state, plugin_manager)
    assert switch_to_english.log.answers[-1]["text"] == t("language_updated", "en")

    help_button = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text=f"❓ {t('help', 'en')}",
    )
    await settings_entrypoint(help_button, state, plugin_manager)
    assert help_button.log.answers[-1]["text"].startswith(t("help_panel_intro", "en"))


@pytest.mark.asyncio
async def test_start_command_preserves_saved_language(
    patch_db_dependencies,
    db_session,
    fake_message_factory,
    fsm_context_factory,
) -> None:
    db_session.add(
        SubscriptionRequest(
            tg_user_id=2223,
            username="tester_en",
            full_name="Test User",
            status=SubscriptionStatus.APPROVED.value,
        )
    )

    from bot.db.models import User as UserModel

    db_session.add(UserModel(tg_user_id=2223, username="tester_en", full_name="Test User", language_code="en"))
    await db_session.commit()

    state = fsm_context_factory(user_id=2223, chat_id=7005)
    message = fake_message_factory(chat_id=7005, chat_type="private", user_id=2223, text="/start")

    await start_handler(message, state)

    assert message.log.answers[0]["text"] == t("main_menu", "en")
    labels = [button.text for row in message.log.answers[0]["reply_markup"].keyboard for button in row]
    assert f"⚙ {t('settings', 'en')}" in labels
    assert f"❓ {t('help', 'en')}" in labels


@pytest.mark.asyncio
async def test_start_command_clears_stale_state_before_private_keyboard_navigation(
    patch_db_dependencies,
    db_session,
    fake_message_factory,
    fsm_context_factory,
    plugin_manager,
) -> None:
    db_session.add(
        SubscriptionRequest(
            tg_user_id=2224,
            username="tester_state",
            full_name="Test User",
            status=SubscriptionStatus.APPROVED.value,
        )
    )
    await db_session.commit()

    state = fsm_context_factory(user_id=2224, chat_id=2224)
    await state.set_state(SettingsFlow.announcement_schedule_text)

    start_message = fake_message_factory(chat_id=2224, chat_type="private", user_id=2224, text="/start")
    await start_handler(start_message, state)
    assert await state.get_state() is None

    settings_button = fake_message_factory(
        chat_id=2224,
        chat_type="private",
        user_id=2224,
        text=f"⚙ {t('settings', 'ar')}",
    )
    await settings_entrypoint(settings_button, state, plugin_manager)

    assert settings_button.log.answers[-1]["text"] == t("select_group", "ar")


@pytest.mark.asyncio
async def test_settings_tab_routes_from_private_submenu_state(
    patch_db_dependencies,
    seeded_group,
    fake_message_factory,
    fsm_context_factory,
    plugin_manager,
) -> None:
    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])
    await state.set_state(SettingsFlow.help_menu)

    settings_button = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text=f"⚙ {t('settings', 'ar')}",
    )

    await settings_entrypoint(settings_button, state, plugin_manager)

    assert settings_button.log.answers[-1]["text"] == t("select_group", "ar")
    assert await state.get_state() == SettingsFlow.selecting_group.state


@pytest.mark.asyncio
async def test_language_command_opens_private_language_keyboard(
    patch_db_dependencies,
    seeded_group,
    fake_message_factory,
    fsm_context_factory,
) -> None:
    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])
    message = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="/lang",
    )

    await language_handler(message, state)

    assert message.log.answers[-1]["text"] == t("choose_language", "ar")
    labels = [button.text for row in message.log.answers[-1]["reply_markup"].keyboard for button in row]
    assert f"🇺🇸 {t('language_en', 'ar')}" in labels
    assert f"🇸🇦 {t('language_ar', 'ar')}" in labels
    assert await state.get_state() == SettingsFlow.language_menu.state


@pytest.mark.asyncio
async def test_language_command_accepts_direct_language_argument(
    patch_db_dependencies,
    seeded_group,
    db_session,
    fake_message_factory,
    fsm_context_factory,
) -> None:
    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])
    await state.set_state(SettingsFlow.help_menu)
    message = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="/lang en",
    )

    await language_handler(message, state)

    assert message.log.answers[-1]["text"] == t("language_updated", "en")
    labels = [button.text for row in message.log.answers[-1]["reply_markup"].keyboard for button in row]
    assert f"⚙ {t('settings', 'en')}" in labels
    assert await state.get_state() is None

    from bot.db.models import User as UserModel

    user = (await db_session.execute(select(UserModel).where(UserModel.tg_user_id == seeded_group["user_id"]))).scalar_one()
    assert user.language_code == "en"


@pytest.mark.asyncio
async def test_private_keyboard_button_with_bidi_marks_still_routes(
    patch_db_dependencies,
    seeded_group,
    fake_message_factory,
    fsm_context_factory,
    plugin_manager,
) -> None:
    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])
    message = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text=f"\u200f❓ {t('help', 'ar')}\u200f",
    )

    await settings_entrypoint(message, state, plugin_manager)

    assert message.log.answers[-1]["text"].startswith(t("help_panel_intro", "ar"))


@pytest.mark.asyncio
async def test_private_idle_no_match_uses_fallback_response(
    patch_db_dependencies,
    seeded_group,
    db_session,
    fake_message_factory,
    fsm_context_factory,
    plugin_manager,
) -> None:
    db_session.add(
        SubscriptionRequest(
            tg_user_id=seeded_group["user_id"],
            username="owner",
            full_name="Owner",
            status=SubscriptionStatus.APPROVED.value,
        )
    )
    await db_session.commit()
    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])
    message = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="non-matching-private-text",
    )

    await settings_entrypoint(message, state, plugin_manager)

    assert message.log.answers[-1]["text"] == t("main_menu", "ar")


@pytest.mark.asyncio
async def test_start_command_returns_main_menu(
    patch_db_dependencies,
    db_session,
    fake_message_factory,
    fsm_context_factory,
) -> None:
    db_session.add(
        SubscriptionRequest(
            tg_user_id=2222,
            username="tester",
            full_name="Test User",
            status=SubscriptionStatus.APPROVED.value,
        )
    )
    await db_session.commit()
    state = fsm_context_factory(user_id=2222, chat_id=7001)
    message = fake_message_factory(chat_id=7001, chat_type="private", user_id=2222, text="/start")

    await start_handler(message, state)

    assert len(message.log.answers) == 1
    assert message.log.answers[0]["text"] == t("main_menu", "ar")
    keyboard_rows = message.log.answers[0]["reply_markup"].keyboard
    assert all(len(row) <= 2 for row in keyboard_rows)
    labels = [button.text for row in keyboard_rows for button in row]
    assert f"🗂 {t('group_management', 'ar')}" in labels
    assert f"⚙ {t('settings', 'ar')}" in labels
    assert f"📢 {t('announcements', 'ar')}" in labels
    assert f"✅ {t('tasks', 'ar')}" in labels
    assert f"🤖 {t('agents', 'ar')}" in labels
    assert f"❓ {t('help', 'ar')}" in labels
    assert f"🌐 {t('language', 'ar')}" in labels
    assert isinstance(message.bot.chat_menu_buttons[-1]["menu_button"], MenuButtonWebApp)


@pytest.mark.asyncio
async def test_private_start_hides_dashboard_for_unsubscribed_user(
    patch_db_dependencies,
    fake_message_factory,
    fsm_context_factory,
) -> None:
    state = fsm_context_factory(user_id=3333, chat_id=7002)
    message = fake_message_factory(chat_id=7002, chat_type="private", user_id=3333, text="/start")

    await start_handler(message, state)

    assert len(message.log.answers) == 2
    assert message.log.answers[0]["text"] == t("main_menu", "ar")
    assert message.log.answers[0]["reply_markup"].remove_keyboard is True
    assert message.log.answers[1]["text"] == t("subscription_mandate_prompt", "ar")
    assert isinstance(message.bot.chat_menu_buttons[-1]["menu_button"], MenuButtonCommands)


@pytest.mark.asyncio
async def test_start_command_uses_agents_webapp_for_agents_bot(
    patch_db_dependencies,
    db_session,
    fake_message_factory,
    fsm_context_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOT_APP_KIND", "agents")
    monkeypatch.setenv("AGENTS_WEBAPP_URL", "https://example.com/webapp/agents")
    monkeypatch.setenv("WEBAPP_URL", "")
    monkeypatch.setenv("DASHBOARD_URL", "")
    get_settings.cache_clear()

    db_session.add(
        SubscriptionRequest(
            tg_user_id=2223,
            username="agent-user",
            full_name="Agent User",
            status=SubscriptionStatus.APPROVED.value,
        )
    )
    await db_session.commit()
    state = fsm_context_factory(user_id=2223, chat_id=7005)
    message = fake_message_factory(chat_id=7005, chat_type="private", user_id=2223, text="/start")

    await start_handler(message, state)
    keyboard_rows = message.log.answers[0]["reply_markup"].keyboard
    open_app_button = keyboard_rows[0][0]
    assert open_app_button.web_app.url == "https://example.com/webapp/agents"
    assert open_app_button.text == f"🤖 {t('open_agents_miniapp', 'ar')}"
    assert message.bot.chat_menu_buttons[-1]["menu_button"].web_app.url == "https://example.com/webapp/agents"

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_group_start_hides_buttons_for_non_admin(
    patch_db_dependencies,
    fake_message_factory,
    fsm_context_factory,
) -> None:
    class _MemberBot:
        async def get_chat_member(self, _chat_id: int, _user_id: int):
            return SimpleNamespace(status="member")

    message = fake_message_factory(
        chat_id=-1007001,
        chat_type="supergroup",
        user_id=2222,
        text="/start",
        bot=_MemberBot(),
    )

    state = fsm_context_factory(user_id=2222, chat_id=-1007001)
    await start_handler(message, state)

    assert len(message.log.answers) == 1
    assert message.log.answers[0]["reply_markup"].remove_keyboard is True


@pytest.mark.asyncio
async def test_group_help_hides_buttons_for_non_admin(
    patch_db_dependencies,
    fake_message_factory,
    fsm_context_factory,
) -> None:
    class _MemberBot:
        async def get_chat_member(self, _chat_id: int, _user_id: int):
            return SimpleNamespace(status="member")

    message = fake_message_factory(
        chat_id=-1007001,
        chat_type="supergroup",
        user_id=2222,
        text="/help",
        bot=_MemberBot(),
    )

    state = fsm_context_factory(user_id=2222, chat_id=-1007001)
    await help_handler(message, state)

    assert len(message.log.answers) == 1
    assert message.log.answers[0]["reply_markup"].remove_keyboard is True


@pytest.mark.asyncio
async def test_group_dashboard_hides_buttons_for_non_admin(
    patch_db_dependencies,
    fake_message_factory,
    fsm_context_factory,
) -> None:
    class _MemberBot:
        async def get_chat_member(self, _chat_id: int, _user_id: int):
            return SimpleNamespace(status="member")

    message = fake_message_factory(
        chat_id=-1007001,
        chat_type="supergroup",
        user_id=2222,
        text="/dashboard",
        bot=_MemberBot(),
    )

    state = fsm_context_factory(user_id=2222, chat_id=-1007001)
    await dashboard_handler(message, state)

    assert len(message.log.answers) == 1
    assert message.log.answers[0]["reply_markup"].remove_keyboard is True


@pytest.mark.asyncio
async def test_private_dashboard_hides_buttons_for_unsubscribed_user(
    patch_db_dependencies,
    fake_message_factory,
    fsm_context_factory,
) -> None:
    state = fsm_context_factory(user_id=4444, chat_id=7003)
    message = fake_message_factory(
        chat_id=7003,
        chat_type="private",
        user_id=4444,
        text="/dashboard",
    )

    await dashboard_handler(message, state)

    assert len(message.log.answers) == 1
    assert message.log.answers[0]["text"] == t("subscription_mandate_prompt", "ar")
    assert message.log.answers[0]["reply_markup"].remove_keyboard is True


@pytest.mark.asyncio
async def test_private_scraper_command_opens_scraper_route(
    patch_db_dependencies,
    db_session,
    seeded_group,
    fake_message_factory,
    fsm_context_factory,
) -> None:
    db_session.add(
        SubscriptionRequest(
            tg_user_id=seeded_group["user_id"],
            username="owner",
            full_name="Owner",
            status=SubscriptionStatus.APPROVED.value,
        )
    )
    await db_session.commit()

    message = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="/scraper",
    )

    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])
    await scraper_handler(message, state)

    assert len(message.log.answers) == 1
    assert message.log.answers[0]["text"] == t("scraper_open_prompt", "ar")
    keyboard = message.log.answers[0]["reply_markup"]
    assert keyboard.inline_keyboard[0][0].web_app.url.endswith("#/scraper")


@pytest.mark.asyncio
async def test_private_help_hides_buttons_for_unsubscribed_user(
    patch_db_dependencies,
    fake_message_factory,
    fsm_context_factory,
) -> None:
    state = fsm_context_factory(user_id=5555, chat_id=7004)
    message = fake_message_factory(
        chat_id=7004,
        chat_type="private",
        user_id=5555,
        text="/help",
    )

    await help_handler(message, state)

    assert len(message.log.answers) == 1
    assert message.log.answers[0]["text"] == t("subscription_mandate_prompt", "ar")
    assert message.log.answers[0]["reply_markup"].remove_keyboard is True


@pytest.mark.asyncio
async def test_group_settings_command_hides_buttons_for_non_admin(
    patch_db_dependencies,
    fake_message_factory,
    fsm_context_factory,
) -> None:
    class _MemberBot:
        async def get_chat_member(self, _chat_id: int, _user_id: int):
            return SimpleNamespace(status="member")

    message = fake_message_factory(
        chat_id=-1007001,
        chat_type="supergroup",
        user_id=2222,
        text="/settings",
        bot=_MemberBot(),
    )

    state = fsm_context_factory(user_id=2222, chat_id=-1007001)
    await settings_handler(message, state)

    assert len(message.log.answers) == 1
    assert message.log.answers[0]["reply_markup"].remove_keyboard is True


@pytest.mark.asyncio
async def test_private_settings_command_opens_group_selector(
    patch_db_dependencies,
    db_session,
    seeded_group,
    fake_message_factory,
    fsm_context_factory,
) -> None:
    db_session.add(
        SubscriptionRequest(
            tg_user_id=seeded_group["user_id"],
            username="owner",
            full_name="Owner",
            status=SubscriptionStatus.APPROVED.value,
        )
    )
    await db_session.commit()

    message = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="/settings",
    )

    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])
    await settings_handler(message, state)

    assert len(message.log.answers) == 1
    assert message.log.answers[0]["text"] == t("select_group", "ar")
    assert await state.get_state() == SettingsFlow.selecting_group.state

@pytest.mark.asyncio
async def test_settings_button_loads_group_selector(
    patch_db_dependencies,
    seeded_group,
    fsm_context_factory,
    menu_engine,
    fake_message_factory,
    fake_callback_factory,
) -> None:
    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])
    host_message = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="open",
    )
    callback = fake_callback_factory(
        data="menu:settings",
        from_user_id=seeded_group["user_id"],
        message=host_message,
    )

    await menu_settings(callback, state, menu_engine)

    assert len(host_message.log.edits) == 1
    assert host_message.log.edits[0]["text"] == t("select_group", "en")
    assert host_message.log.callback_answers[-1]["text"] is None


@pytest.mark.asyncio
async def test_settings_entrypoint_ignores_group_messages(
    patch_db_dependencies,
    fsm_context_factory,
    fake_message_factory,
    plugin_manager,
) -> None:
    state = fsm_context_factory(user_id=1001, chat_id=-10012345)
    message = fake_message_factory(
        chat_id=-10012345,
        chat_type="supergroup",
        user_id=1001,
        text="https://example.com",
    )

    await settings_entrypoint(message, state, plugin_manager)

    assert message.log.answers == []
    assert message.log.edits == []


@pytest.mark.asyncio
async def test_mock_telegram_update_generator(telegram_update_factory) -> None:
    update = telegram_update_factory(text="/start", user_id=9991, chat_id=9992)
    assert update.message is not None
    assert update.message.text == "/start"
    assert update.message.from_user.id == 9991


def test_main_menu_inline_layout(menu_engine) -> None:
    markup = menu_engine.main_menu("en")
    labels = [btn.text for row in markup.inline_keyboard for btn in row]
    assert labels == [
        "🛡 Moderation",
        "👥 Members",
        "📊 Group Stats",
        "⚙ Settings",
        "📢 Announcements",
        "🤖 Agents",
        "❓ Help",
    ]


def test_main_menu_keyboard_includes_tasks_webapp_button() -> None:
    markup = main_menu_keyboard("en", dashboard_url="https://example.com/webapp?group=7")
    assert all(len(row) <= 2 for row in markup.keyboard)
    labels = [button.text for row in markup.keyboard for button in row]

    assert "⚙ Settings" in labels
    assert "✅ Tasks" in labels
    assert "📢 Announcements" in labels
    assert "🗂 Group Management" in labels
    assert "📱 Open App" not in labels
    assert "📋 Open Admin" in labels
    assert "🤖 Open Agents" not in labels

    webapp_buttons = {
        button.text: button.web_app.url
        for row in markup.keyboard
        for button in row
        if button.web_app is not None
    }
    assert webapp_buttons["📋 Open Admin"] == "https://example.com/webapp?group=7"


def test_tasks_menu_keyboard_is_standalone() -> None:
    markup = tasks_menu_keyboard("en", include_tabs=False)
    labels = [button.text for row in markup.keyboard for button in row]

    assert labels == [
        "➕ Add Reply Task",
        "📣 Add Notify Task",
        "📋 Task Catalog",
        "🧩 Assigned Tasks",
        "🗑 Delete Task",
        "🏠 Main Menu",
        "⬅ Back",
    ]


def test_announcements_menu_keyboard_includes_edit_and_delete() -> None:
    from bot.keyboards.reply.menus import announcements_menu_keyboard

    markup = announcements_menu_keyboard("en", include_tabs=False)
    labels = [button.text for row in markup.keyboard for button in row]

    assert "✏️ Edit Scheduled Message" in labels
    assert "🗑 Delete Scheduled Message" in labels


def test_task_executor_keyboard_is_standalone() -> None:
    markup = task_executor_keyboard("en", include_tabs=False)
    labels = [button.text for row in markup.keyboard for button in row]

    assert labels == ["🤖 Bot", "👤 Agent", "⬅ Back"]


def test_task_group_keyboard_is_standalone() -> None:
    markup = task_group_keyboard(paginate(["Group A", "Group B"], page=1, page_size=10), "en", include_tabs=False)
    labels = [button.text for row in markup.keyboard for button in row]

    assert labels == ["Group A", "Group B", "Page 1/1", "⬅ Back"]


def test_task_reply_visibility_keyboard_is_standalone() -> None:
    from bot.keyboards.reply.menus import task_reply_visibility_keyboard

    markup = task_reply_visibility_keyboard("en", include_tabs=False)
    labels = [button.text for row in markup.keyboard for button in row]

    assert labels == ["🌐 Public", "🔒 Private", "⬅ Back"]


def test_task_delete_keyboard_is_standalone() -> None:
    markup = task_delete_keyboard(["Task A", "Task B"], "en", include_tabs=False)
    labels = [button.text for row in markup.keyboard for button in row]

    assert labels == ["Task A", "Task B", "⬅ Back"]


def test_task_delete_confirm_keyboard_is_standalone() -> None:
    markup = task_delete_confirm_keyboard("en", include_tabs=False)
    labels = [button.text for row in markup.keyboard for button in row]

    assert labels == ["✅ Confirm", "⬅ Back"]


def test_task_agent_keyboard_lists_agents() -> None:
    markup = task_agent_keyboard(["👤 sales-bot", "👤 ops-bot"], "en", include_tabs=False)
    labels = [button.text for row in markup.keyboard for button in row]

    assert labels == ["👤 sales-bot", "👤 ops-bot", "⬅ Back"]


def test_task_group_keyboard_lists_groups_with_pagination() -> None:
    markup = task_group_keyboard(paginate([f"Group {index}" for index in range(1, 12)], page=2, page_size=10), "en", include_tabs=False)
    labels = [button.text for row in markup.keyboard for button in row]

    assert "Group 11" in labels
    assert "◀ Prev" in labels
    assert "Page 2/2" in labels
    assert "⬅ Back" in labels


@pytest.mark.asyncio
async def test_tasks_flow_can_save_reply_task_for_bot(
    patch_db_dependencies,
    seeded_group,
    fake_message_factory,
    fsm_context_factory,
    plugin_manager,
    session_factory,
) -> None:
    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])

    entry_message = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="✅ المهام",
    )
    await settings_entrypoint(entry_message, state, plugin_manager)
    assert entry_message.log.answers[-1]["text"] == t("task_executor_prompt", "ar")

    executor_select = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="🤖 البوت",
    )
    await settings_entrypoint(executor_select, state, plugin_manager)
    assert executor_select.log.answers[-1]["text"] == t("task_group_prompt", "ar")

    group_message = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="QA Group",
    )
    await settings_entrypoint(group_message, state, plugin_manager)
    assert t("tasks", "ar") in group_message.log.answers[-1]["text"]

    add_message = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="➕ إضافة مهمة رد",
    )
    await settings_entrypoint(add_message, state, plugin_manager)
    assert add_message.log.answers[-1]["text"] == t("task_keyword_prompt", "ar")

    keyword_message = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="price",
    )
    await settings_entrypoint(keyword_message, state, plugin_manager)
    assert keyword_message.log.answers[-1]["text"] == t("task_template_prompt", "ar")

    template_message = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="Pricing team will reply soon.",
    )
    await settings_entrypoint(template_message, state, plugin_manager)
    assert template_message.log.answers[-1]["text"] == (
        f"{t('task_saved', 'ar')}\n\n"
        f"{t('task_saved_details', 'ar', keyword='price', executor=t('task_executor_bot', 'ar'))}"
    )

    list_message = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="🧩 المهام المعيّنة",
    )
    await settings_entrypoint(list_message, state, plugin_manager)
    assert "price -> Pricing team will reply soon." in list_message.log.answers[-1]["text"]

    async with session_factory() as session:
        assignments = await TaskService(session, dispatch_agent_job=lambda _job_id: None).list_assignments(
            actor_user_id=seeded_group["user_id"],
            group_id=seeded_group["group_id"],
        )
    assert assignments[0]["task_key"] == "reply_message"
    assert assignments[0]["conditions"] == {"text_contains": "price"}
    assert assignments[0]["executor_type"] == "bot"


@pytest.mark.asyncio
async def test_tasks_flow_can_save_notify_task(
    patch_db_dependencies,
    seeded_group,
    fake_message_factory,
    fsm_context_factory,
    plugin_manager,
    session_factory,
) -> None:
    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])

    entry_message = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="✅ المهام",
    )
    await settings_entrypoint(entry_message, state, plugin_manager)

    executor_select = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="🤖 البوت",
    )
    await settings_entrypoint(executor_select, state, plugin_manager)

    group_message = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="QA Group",
    )
    await settings_entrypoint(group_message, state, plugin_manager)

    add_message = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="📣 إضافة مهمة إشعار",
    )
    await settings_entrypoint(add_message, state, plugin_manager)

    keyword_message = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="urgent, escalated\nsev1",
    )
    await settings_entrypoint(keyword_message, state, plugin_manager)

    destination_message = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="123456",
    )
    await settings_entrypoint(destination_message, state, plugin_manager)

    delivery_mode_message = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="📝↪️ نص + إعادة توجيه",
    )
    await settings_entrypoint(delivery_mode_message, state, plugin_manager)

    template_message = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="Escalate: {text}",
    )
    await settings_entrypoint(template_message, state, plugin_manager)

    delete_after_message = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="45",
    )
    await settings_entrypoint(delete_after_message, state, plugin_manager)
    assert t("task_notify_saved", "ar") in delete_after_message.log.answers[-1]["text"]

    async with session_factory() as session:
        assignments = await TaskService(session, dispatch_agent_job=lambda _job_id: None).list_assignments(
            actor_user_id=seeded_group["user_id"],
            group_id=seeded_group["group_id"],
        )
    assert assignments[0]["task_key"] == "notify_destination"
    assert assignments[0]["config"]["destination"] == "123456"
    assert assignments[0]["config"]["delivery_mode"] == "text_and_forward"
    assert assignments[0]["config"]["message_template"] == "Escalate: {text}"
    assert assignments[0]["config"]["delete_after_seconds"] == 45
    assert assignments[0]["conditions"]["text_contains_any"] == ["urgent", "escalated", "sev1"]


@pytest.mark.asyncio
async def test_tasks_flow_can_save_notify_task_with_copy_only_mode(
    patch_db_dependencies,
    seeded_group,
    fake_message_factory,
    fsm_context_factory,
    plugin_manager,
    session_factory,
) -> None:
    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])

    for text in [
        "✅ المهام",
        "🤖 البوت",
        "QA Group",
        "📣 إضافة مهمة إشعار",
        "urgent",
        "ops_room",
        "📋 نسخ فقط",
        "0",
    ]:
        message = fake_message_factory(
            chat_id=seeded_group["user_id"],
            chat_type="private",
            user_id=seeded_group["user_id"],
            text=text,
        )
        await settings_entrypoint(message, state, plugin_manager)

    async with session_factory() as session:
        assignments = await TaskService(session, dispatch_agent_job=lambda _job_id: None).list_assignments(
            actor_user_id=seeded_group["user_id"],
            group_id=seeded_group["group_id"],
        )
    assert assignments[0]["task_key"] == "notify_destination"
    assert assignments[0]["config"]["destination"] == "ops_room"
    assert assignments[0]["config"]["delivery_mode"] == "copy"
    assert "message_template" not in assignments[0]["config"]
    assert assignments[0]["config"]["delete_after_seconds"] == 0


@pytest.mark.asyncio
async def test_tasks_flow_can_save_notify_task_with_forward_only_mode(
    patch_db_dependencies,
    seeded_group,
    fake_message_factory,
    fsm_context_factory,
    plugin_manager,
    session_factory,
) -> None:
    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])

    for text in [
        "✅ المهام",
        "🤖 البوت",
        "QA Group",
        "📣 إضافة مهمة إشعار",
        "urgent",
        "987654",
        "↪️ إعادة توجيه فقط",
        "0",
    ]:
        message = fake_message_factory(
            chat_id=seeded_group["user_id"],
            chat_type="private",
            user_id=seeded_group["user_id"],
            text=text,
        )
        await settings_entrypoint(message, state, plugin_manager)

    async with session_factory() as session:
        assignments = await TaskService(session, dispatch_agent_job=lambda _job_id: None).list_assignments(
            actor_user_id=seeded_group["user_id"],
            group_id=seeded_group["group_id"],
        )
    assert assignments[0]["task_key"] == "notify_destination"
    assert assignments[0]["config"]["destination"] == "987654"
    assert assignments[0]["config"]["delivery_mode"] == "forward"
    assert "message_template" not in assignments[0]["config"]
    assert assignments[0]["config"]["delete_after_seconds"] == 0


@pytest.mark.asyncio
async def test_tasks_flow_can_save_reply_task_for_agent(
    patch_db_dependencies,
    seeded_group,
    db_session,
    fake_message_factory,
    fsm_context_factory,
    plugin_manager,
    session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = Agent(
        group_id=seeded_group["group_id"],
        telegram_user_id=90001,
        external_account_id="sales-bot",
        status="active",
        auth_state="active",
        session_string="session",
        details={},
    )
    db_session.add(agent)
    await db_session.commit()

    async def _fake_agent_map(_actor_user_id: int) -> dict[str, int]:
        return {"👤 sales-bot": agent.id}

    async def _fake_group_map(_actor_user_id: int, _agent_id: int) -> dict[str, dict[str, int | str | None]]:
        return {
            "QA Group": {
                "group_id": seeded_group["group_id"],
                "tg_group_id": seeded_group["tg_group_id"],
                "title": "QA Group",
            }
        }

    monkeypatch.setattr(reply_settings, "_all_active_agent_display_map", _fake_agent_map)
    monkeypatch.setattr(reply_settings, "_agent_task_group_display_map", _fake_group_map)

    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])

    messages = [
        "✅ المهام",
        "👤 وكيل",
        "👤 sales-bot",
        "QA Group",
        "➕ إضافة مهمة رد",
        "quote",
        "🌐 علني",
        "Agent will help shortly",
    ]
    for text in messages:
        message = fake_message_factory(
            chat_id=seeded_group["user_id"],
            chat_type="private",
            user_id=seeded_group["user_id"],
            text=text,
        )
        await settings_entrypoint(message, state, plugin_manager)

    async with session_factory() as session:
        assignments = await TaskService(session, dispatch_agent_job=lambda _job_id: None).list_assignments(
            actor_user_id=seeded_group["user_id"],
            group_id=seeded_group["group_id"],
        )
    assert assignments[0]["executor_type"] == "agent"
    assert assignments[0]["agent_id"] == agent.id
    assert assignments[0]["config"]["reply_mode"] == "public"


@pytest.mark.asyncio
async def test_tasks_flow_paginates_bot_groups(
    patch_db_dependencies,
    seeded_group,
    fake_message_factory,
    fsm_context_factory,
    plugin_manager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_bot_group_map() -> dict[str, dict[str, int | str | None]]:
        return {
            f"Group {index:02d}": {
                "group_id": index,
                "tg_group_id": -100000 - index,
                "title": f"Group {index:02d}",
            }
            for index in range(1, 13)
        }

    monkeypatch.setattr(reply_settings, "_bot_task_group_display_map", _fake_bot_group_map)

    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])

    open_tasks = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="✅ المهام",
    )
    await settings_entrypoint(open_tasks, state, plugin_manager)

    choose_bot = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="🤖 البوت",
    )
    await settings_entrypoint(choose_bot, state, plugin_manager)

    first_page_labels = [button.text for row in choose_bot.log.answers[-1]["reply_markup"].keyboard for button in row]
    assert "Group 01" in first_page_labels
    assert "Group 10" in first_page_labels
    assert "Group 11" not in first_page_labels
    assert f"{t('next', 'ar')} ▶" in first_page_labels

    next_page = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text=f"{t('next', 'ar')} ▶",
    )
    await settings_entrypoint(next_page, state, plugin_manager)

    second_page_labels = [button.text for row in next_page.log.answers[-1]["reply_markup"].keyboard for button in row]
    assert "Group 11" in second_page_labels
    assert "Group 12" in second_page_labels
    assert "Group 10" not in second_page_labels
    assert f"◀ {t('prev', 'ar')}" in second_page_labels


@pytest.mark.asyncio
async def test_tasks_flow_paginates_agent_groups(
    patch_db_dependencies,
    seeded_group,
    db_session,
    fake_message_factory,
    fsm_context_factory,
    plugin_manager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = Agent(
        group_id=seeded_group["group_id"],
        telegram_user_id=90002,
        external_account_id="ops-bot",
        status="active",
        auth_state="active",
        session_string="session",
        details={},
    )
    db_session.add(agent)
    await db_session.commit()

    async def _fake_agent_map(_actor_user_id: int) -> dict[str, int]:
        return {"👤 ops-bot": agent.id}

    async def _fake_group_map(_actor_user_id: int, _agent_id: int) -> dict[str, dict[str, int | str | None]]:
        return {
            f"Agent Group {index:02d}": {
                "group_id": None,
                "tg_group_id": -200000 - index,
                "title": f"Agent Group {index:02d}",
            }
            for index in range(1, 13)
        }

    monkeypatch.setattr(reply_settings, "_all_active_agent_display_map", _fake_agent_map)
    monkeypatch.setattr(reply_settings, "_agent_task_group_display_map", _fake_group_map)

    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])

    for text in ["✅ المهام", "👤 وكيل"]:
        message = fake_message_factory(
            chat_id=seeded_group["user_id"],
            chat_type="private",
            user_id=seeded_group["user_id"],
            text=text,
        )
        await settings_entrypoint(message, state, plugin_manager)

    choose_agent = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="👤 ops-bot",
    )
    await settings_entrypoint(choose_agent, state, plugin_manager)

    first_page_labels = [button.text for row in choose_agent.log.answers[-1]["reply_markup"].keyboard for button in row]
    assert "Agent Group 01" in first_page_labels
    assert "Agent Group 10" in first_page_labels
    assert "Agent Group 11" not in first_page_labels
    assert f"{t('next', 'ar')} ▶" in first_page_labels

    next_page = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text=f"{t('next', 'ar')} ▶",
    )
    await settings_entrypoint(next_page, state, plugin_manager)

    second_page_labels = [button.text for row in next_page.log.answers[-1]["reply_markup"].keyboard for button in row]
    assert "Agent Group 11" in second_page_labels
    assert "Agent Group 12" in second_page_labels
    assert "Agent Group 10" not in second_page_labels


@pytest.mark.asyncio
async def test_tasks_flow_can_delete_task_with_confirmation(
    patch_db_dependencies,
    seeded_group,
    fake_message_factory,
    fsm_context_factory,
    plugin_manager,
    session_factory,
) -> None:
    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])

    messages = [
        "✅ المهام",
        "🤖 البوت",
        "QA Group",
        "➕ إضافة مهمة رد",
        "price",
        "Pricing team will reply soon.",
    ]
    for text in messages:
        message = fake_message_factory(
            chat_id=seeded_group["user_id"],
            chat_type="private",
            user_id=seeded_group["user_id"],
            text=text,
        )
        await settings_entrypoint(message, state, plugin_manager)

    delete_open = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="🗑 حذف مهمة",
    )
    await settings_entrypoint(delete_open, state, plugin_manager)
    assert delete_open.log.answers[-1]["text"] == t("task_delete_prompt", "ar")

    choose_task = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="🗑 reply_message | bot | price",
    )
    await settings_entrypoint(choose_task, state, plugin_manager)
    assert t("task_delete_confirm", "ar") in choose_task.log.answers[-1]["text"]

    confirm_delete = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text=f"✅ {t('confirm', 'ar')}",
    )
    await settings_entrypoint(confirm_delete, state, plugin_manager)
    assert confirm_delete.log.answers[-1]["text"] == t("task_deleted", "ar")

    async with session_factory() as session:
        assignments = await TaskService(session, dispatch_agent_job=lambda _job_id: None).list_assignments(
            actor_user_id=seeded_group["user_id"],
            group_id=seeded_group["group_id"],
        )
    assert assignments == []


@pytest.mark.asyncio
async def test_moderation_menu_buttons(menu_engine, fake_message_factory, fake_callback_factory) -> None:
    host_message = fake_message_factory(chat_id=1001, chat_type="private", user_id=1001, text="open")
    callback = fake_callback_factory(data="menu:moderation", from_user_id=1001, message=host_message)

    await menu_moderation(callback, menu_engine)

    assert host_message.log.edits[-1]["text"] == t("moderation_panel", "en")
    buttons = [btn.text for row in host_message.log.edits[-1]["reply_markup"].inline_keyboard for btn in row]
    assert "🚫 Ban User" in buttons
    assert "⏳ Mute User" in buttons
    assert "⚠ Warnings" in buttons
    assert "📣 Anti Ads" in buttons


@pytest.mark.asyncio
async def test_agents_panel_group_then_link_account(
    patch_db_dependencies,
    seeded_group,
    fsm_context_factory,
    fake_message_factory,
    plugin_manager,
    monkeypatch,
) -> None:
    monkeypatch.setattr(reply_settings, "get_agent_auth_service", lambda: FakeTelegramAgentAuthService())
    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])

    agents_click = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text=f"🤖 {t('agents', 'ar')}",
    )
    await settings_entrypoint(agents_click, state, plugin_manager)
    assert agents_click.log.answers[-1]["text"] == t("no_linked_accounts", "ar")

    link_click = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text=f"⬅ {t('back', 'ar')}",
    )
    await settings_entrypoint(link_click, state, plugin_manager)
    assert link_click.log.answers[-1]["text"] == t("main_menu", "ar")

    reopen_agents = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text=f"🤖 {t('agents', 'ar')}",
    )
    await settings_entrypoint(reopen_agents, state, plugin_manager)

    link_account = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text=f"🔗 {t('link_account', 'ar')}",
    )
    await settings_entrypoint(link_account, state, plugin_manager)
    assert link_account.log.answers[-1]["text"] == t("agent_link_prompt", "ar")

    phone_submit = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="+15550000001",
    )
    await settings_entrypoint(phone_submit, state, plugin_manager)
    assert phone_submit.log.answers[-1]["text"] == t("agent_code_prompt", "ar")

    code_submit = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="12345",
    )
    await settings_entrypoint(code_submit, state, plugin_manager)
    assert any(answer["text"] == t("agent_link_success", "ar") for answer in code_submit.log.answers)

    agents_list_open = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text=f"🤖 {t('agents', 'ar')}",
    )
    await settings_entrypoint(agents_list_open, state, plugin_manager)
    labels = [b.text for row in agents_list_open.log.answers[-1]["reply_markup"].keyboard for b in row]
    assert any("salesbot" in label for label in labels)

    select_agent = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text=next(label for label in labels if "salesbot" in label),
    )
    await settings_entrypoint(select_agent, state, plugin_manager)
    assert t("agent_selected_title", "ar") in select_agent.log.answers[-1]["text"]
    action_labels = [b.text for row in select_agent.log.answers[-1]["reply_markup"].keyboard for b in row]
    assert f"⚙ {t('agent_jobs', 'ar')}" in action_labels
    assert f"➕ {t('create_job', 'ar')}" in action_labels
    assert f"🔌 {t('unlink_account', 'ar')}" in action_labels

    unlink_click = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text=f"🔌 {t('unlink_account', 'ar')}",
    )
    await settings_entrypoint(unlink_click, state, plugin_manager)
    assert t("agent_unlink_confirm", "ar") in unlink_click.log.answers[-1]["text"]

    confirm_unlink = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text=f"✅ {t('confirm', 'ar')}",
    )
    await settings_entrypoint(confirm_unlink, state, plugin_manager)
    assert any(answer["text"] == t("agent_unlink_success", "ar") for answer in confirm_unlink.log.answers)


def test_group_selector_hides_other_buttons() -> None:
    page = paginate([{"id": 1, "title": "QA Group"}], page=1, page_size=10)
    markup = groups_keyboard(page, "en", include_tabs=False)
    labels = [btn.text for row in markup.keyboard for btn in row]
    assert "QA Group" in labels
    assert "🛡 Moderation" not in labels
    assert "📢 Announcements" not in labels


@pytest.mark.asyncio
async def test_members_menu_group_then_members_actions(
    patch_db_dependencies,
    seeded_group,
    fsm_context_factory,
    fake_message_factory,
    plugin_manager,
) -> None:
    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])

    members_click = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text=f"👥 {t('members', 'ar')}",
    )
    await settings_entrypoint(members_click, state, plugin_manager)
    assert members_click.log.answers[-1]["text"] == t("select_group_for_members", "ar")

    select_group = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="QA Group",
    )
    await settings_entrypoint(select_group, state, plugin_manager)
    assert select_group.log.answers[-1]["text"].startswith(t("members", "ar"))
    labels = [b.text for row in select_group.log.answers[-1]["reply_markup"].keyboard for b in row]
    assert f"👑 {t('admin_list', 'ar')}" in labels
    assert f"👥 {t('member_list', 'ar')}" in labels
    assert f"➕ {t('promote', 'ar')}" in labels
    assert f"🌐 {t('language', 'ar')}" in labels
    assert f"🏠 {t('main_menu_btn', 'ar')}" in labels


@pytest.mark.asyncio
async def test_members_menu_admin_list_uses_selected_group(
    patch_db_dependencies,
    seeded_group,
    fsm_context_factory,
    fake_message_factory,
    plugin_manager,
    fake_bot,
) -> None:
    fake_bot.chat_administrators[seeded_group["tg_group_id"]] = [
        SimpleNamespace(
            status="creator",
            user=SimpleNamespace(full_name="Owner User", username="owner"),
        ),
        SimpleNamespace(
            status="administrator",
            user=SimpleNamespace(full_name="Mod User", username="moderator"),
        ),
    ]

    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])
    await state.set_state(SettingsFlow.members_menu)
    await state.update_data(selected_group=seeded_group["group_id"])

    message = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text=f"👑 {t('admin_list', 'ar')}",
        bot=fake_bot,
    )

    await settings_entrypoint(message, state, plugin_manager)

    response = message.log.answers[-1]["text"]
    assert response.startswith(t("admin_list", "ar"))
    assert "QA Group" in response
    assert "Owner User (@owner) [Creator]" in response
    assert "Mod User (@moderator) [Administrator]" in response


@pytest.mark.asyncio
async def test_members_menu_member_list_uses_selected_group_counts(
    patch_db_dependencies,
    seeded_group,
    fsm_context_factory,
    fake_message_factory,
    plugin_manager,
    fake_bot,
) -> None:
    fake_bot.chat_administrators[seeded_group["tg_group_id"]] = [
        SimpleNamespace(
            status="creator",
            user=SimpleNamespace(full_name="Owner User", username="owner"),
        ),
    ]
    fake_bot.member_counts[seeded_group["tg_group_id"]] = 42

    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])
    await state.set_state(SettingsFlow.members_menu)
    await state.update_data(selected_group=seeded_group["group_id"])

    message = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text=f"👥 {t('member_list', 'ar')}",
        bot=fake_bot,
    )

    await settings_entrypoint(message, state, plugin_manager)

    response = message.log.answers[-1]["text"]
    assert response.startswith(t("member_list", "ar"))
    assert "QA Group" in response
    assert f"{t('total_members', 'ar')}: 42" in response
    assert f"{t('total_admins', 'ar')}: 1" in response


@pytest.mark.asyncio
async def test_group_management_stats_opens_group_selector_without_main_menu_items(
    patch_db_dependencies,
    seeded_group,
    fsm_context_factory,
    fake_message_factory,
    plugin_manager,
) -> None:
    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])
    open_menu = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text=f"🗂 {t('group_management', 'ar')}",
    )
    await settings_entrypoint(open_menu, state, plugin_manager)
    assert t("group_management", "ar") in open_menu.log.answers[-1]["text"]

    message = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text=f"📊 {t('stats', 'ar')}",
    )
    await settings_entrypoint(message, state, plugin_manager)

    assert message.log.answers[-1]["text"] == t("select_group_for_analytics", "ar")
    labels = [b.text for row in message.log.answers[-1]["reply_markup"].keyboard for b in row]
    assert "QA Group" in labels
    assert f"📢 {t('announcements', 'ar')}" not in labels
    assert f"🗂 {t('group_management', 'ar')}" not in labels


@pytest.mark.asyncio
async def test_members_menu_promote_action_executes(
    patch_db_dependencies,
    seeded_group,
    fsm_context_factory,
    fake_message_factory,
    plugin_manager,
    fake_bot,
) -> None:
    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])
    await state.set_state(SettingsFlow.members_menu)
    await state.update_data(selected_group=seeded_group["group_id"])

    prompt = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text=f"➕ {t('promote', 'ar')}",
        bot=fake_bot,
    )
    await settings_entrypoint(prompt, state, plugin_manager)
    assert prompt.log.answers[-1]["text"] == t("members_action_prompt", "ar")

    execute = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="7777",
        bot=fake_bot,
    )
    await settings_entrypoint(execute, state, plugin_manager)

    assert fake_bot.promoted_members[0][0] == seeded_group["tg_group_id"]
    assert fake_bot.promoted_members[0][1] == 7777
    assert execute.log.answers[-1]["text"] == t("member_promoted", "ar")


@pytest.mark.asyncio
async def test_members_menu_search_action_shows_member_status(
    patch_db_dependencies,
    seeded_group,
    fsm_context_factory,
    fake_message_factory,
    plugin_manager,
    fake_bot,
) -> None:
    fake_bot.chat_members[(seeded_group["tg_group_id"], 8888)] = SimpleNamespace(
        status="administrator",
        user=SimpleNamespace(full_name="Lookup User", username="lookup"),
    )
    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])
    await state.set_state(SettingsFlow.members_menu)
    await state.update_data(selected_group=seeded_group["group_id"])

    prompt = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text=f"🔎 {t('search_user', 'ar')}",
        bot=fake_bot,
    )
    await settings_entrypoint(prompt, state, plugin_manager)

    execute = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="8888",
        bot=fake_bot,
    )
    await settings_entrypoint(execute, state, plugin_manager)

    response = execute.log.answers[-1]["text"]
    assert response.startswith(t("members_search_result", "ar"))
    assert "Lookup User" in response
    assert "@lookup" in response


@pytest.mark.asyncio
async def test_announcements_panel_schedule_and_bulk_send(
    patch_db_dependencies,
    seeded_group,
    db_session,
    fsm_context_factory,
    fake_message_factory,
    plugin_manager,
    fake_bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reply_settings, "schedule_bot_message_delete", lambda **_: None)
    extra_group = Group(tg_group_id=-1007788001, title="Bulk Group", is_active=True)
    db_session.add(extra_group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=extra_group.id, user_id=seeded_group["user_id"], role="owner"))
    await db_session.commit()

    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])
    entry = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text=f"📢 {t('announcements', 'ar')}",
        bot=fake_bot,
    )
    await settings_entrypoint(entry, state, plugin_manager)
    assert entry.log.answers[-1]["text"] == t("select_group_for_announcements", "ar")

    select_group = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="QA Group",
        bot=fake_bot,
    )
    await settings_entrypoint(select_group, state, plugin_manager)
    assert select_group.log.answers[-1]["text"].startswith(t("announcements", "ar"))

    schedule = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text=f"🗓 {t('schedule_message', 'ar')}",
        bot=fake_bot,
    )
    await settings_entrypoint(schedule, state, plugin_manager)

    schedule_text = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="Scheduled hello",
        bot=fake_bot,
    )
    await settings_entrypoint(schedule_text, state, plugin_manager)

    schedule_time = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="now",
        bot=fake_bot,
    )
    await settings_entrypoint(schedule_time, state, plugin_manager)

    delete_after = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="30",
        bot=fake_bot,
    )
    await settings_entrypoint(delete_after, state, plugin_manager)
    assert (seeded_group["tg_group_id"], "Scheduled hello") in fake_bot.sent_messages

    bulk_select = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text=f"🧩 {t('select_bulk_groups', 'ar')}",
        bot=fake_bot,
    )
    await settings_entrypoint(bulk_select, state, plugin_manager)

    choose_extra = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="☑ Bulk Group",
        bot=fake_bot,
    )
    await settings_entrypoint(choose_extra, state, plugin_manager)

    bulk_message_btn = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text=f"📨 {t('send_bulk_message', 'ar')}",
        bot=fake_bot,
    )
    await settings_entrypoint(bulk_message_btn, state, plugin_manager)

    bulk_text = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="Broadcast hello",
        bot=fake_bot,
    )
    await settings_entrypoint(bulk_text, state, plugin_manager)

    assert (seeded_group["tg_group_id"], "Broadcast hello") in fake_bot.sent_messages
    assert (extra_group.tg_group_id, "Broadcast hello") in fake_bot.sent_messages


@pytest.mark.asyncio
async def test_announcements_flow_can_delete_scheduled_message(
    patch_db_dependencies,
    seeded_group,
    fsm_context_factory,
    fake_message_factory,
    plugin_manager,
    fake_bot,
    session_factory,
) -> None:
    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])
    await state.set_state(SettingsFlow.announcements_menu)
    await state.update_data(selected_group=seeded_group["group_id"])

    async with session_factory() as session:
        await reply_settings.ScheduledMessageService(session).save_entry(
            group_id=seeded_group["group_id"],
            text="Delete me",
            schedule="+10m",
        )

    open_delete = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text=f"🗑 {t('delete_scheduled_message', 'ar')}",
        bot=fake_bot,
    )
    await settings_entrypoint(open_delete, state, plugin_manager)
    assert open_delete.log.answers[-1]["text"] == t("announcement_delete_prompt", "ar")

    option_label = open_delete.log.answers[-1]["reply_markup"].keyboard[0][0].text
    choose_entry = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text=option_label,
        bot=fake_bot,
    )
    await settings_entrypoint(choose_entry, state, plugin_manager)
    assert t("announcement_delete_confirm", "ar") in choose_entry.log.answers[-1]["text"]

    confirm_delete = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text=f"✅ {t('confirm', 'ar')}",
        bot=fake_bot,
    )
    await settings_entrypoint(confirm_delete, state, plugin_manager)
    assert confirm_delete.log.answers[-1]["text"] == t("announcement_deleted", "ar")

    async with session_factory() as session:
        assert await reply_settings.ScheduledMessageService(session).list_entries(group_id=seeded_group["group_id"]) == []


@pytest.mark.asyncio
async def test_help_panel_shows_sections(
    patch_db_dependencies,
    seeded_group,
    fsm_context_factory,
    fake_message_factory,
    plugin_manager,
) -> None:
    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])
    entry = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text=f"❓ {t('help', 'ar')}",
    )
    await settings_entrypoint(entry, state, plugin_manager)
    assert entry.log.answers[-1]["text"].startswith(t("help_panel_intro", "ar"))

    panels = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text=f"🧭 {t('help_panels', 'ar')}",
    )
    await settings_entrypoint(panels, state, plugin_manager)
    assert panels.log.answers[-1]["text"].startswith(t("help_panels", "ar"))


@pytest.mark.asyncio
async def test_help_announcements_mentions_cron_example(
    patch_db_dependencies,
) -> None:
    text = await reply_settings._help_panel_text("ar", "announcements")
    assert "*/15 * * * *" in text


def test_parse_schedule_time_accepts_cron_expression() -> None:
    send_at, cron_expression = reply_settings._parse_schedule_time("*/15 * * * *")

    assert cron_expression == "*/15 * * * *"
    assert send_at.second == 0
    assert send_at.microsecond == 0


def test_send_due_announcements_keeps_recurring_cron_entries(monkeypatch) -> None:
    class FrozenDateTime(datetime):
        @classmethod
        def utcnow(cls) -> "FrozenDateTime":
            return cls(2026, 3, 12, 2, 0)

    entry = {
        "id": "cron-1",
        "text": "Recurring hello",
        "send_at": "2026-03-12T02:00",
        "status": "pending",
        "cron": "*/15 * * * *",
    }

    async def fake_entries(_group_id: int) -> list[dict]:
        return [dict(entry)]

    saved: list[dict] = []

    async def fake_save(_group_id: int, entries: list[dict]) -> None:
        saved[:] = entries

    async def fake_selected_group(_group_id: int):
        return SimpleNamespace(tg_group_id=-100555)

    class FakeScheduledMessageService:
        def __init__(self, session: Any) -> None:
            self.session = session

        async def mark_delivered(self, *, group_id: int, entry_id: str, delivered_at: datetime | None = None) -> dict[str, Any] | None:
            assert entry_id == entry["id"]
            return {
                "id": entry_id,
                "text": entry["text"],
                "send_at": "2026-03-12T02:15",
                "status": "pending",
                "cron": entry["cron"],
            }

    monkeypatch.setattr(reply_settings, "datetime", FrozenDateTime)
    monkeypatch.setattr(reply_settings, "_announcement_entries", fake_entries)
    monkeypatch.setattr(reply_settings, "_save_announcement_entries", fake_save)
    monkeypatch.setattr(reply_settings, "_selected_group", fake_selected_group)
    monkeypatch.setattr(reply_settings, "_schedule_announcement_task", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(reply_settings, "ScheduledMessageService", FakeScheduledMessageService)

    class FakeBot:
        def __init__(self) -> None:
            self.sent_messages: list[tuple[int, str]] = []

        async def send_message(self, chat_id: int, text: str) -> None:
            self.sent_messages.append((chat_id, text))

    class FakeMessage:
        def __init__(self) -> None:
            self.bot = FakeBot()

    message = FakeMessage()

    async def _send():
        return await reply_settings._send_due_announcements(message, 1)

    import asyncio

    sent = asyncio.run(_send())

    assert sent == 1
    assert message.bot.sent_messages == [(-100555, "Recurring hello")]
    assert saved[0]["status"] == "pending"
    assert saved[0]["send_at"] == "2026-03-12T02:15"


@pytest.mark.asyncio
async def test_access_gate_menu_shows_blocked_user_message_preview(
    patch_db_dependencies,
    seeded_group,
    db_session,
    fsm_context_factory,
    fake_message_factory,
    plugin_manager,
) -> None:
    required_group = Group(tg_group_id=-100778899, title="Required Group", is_active=True)
    db_session.add(required_group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=required_group.id, user_id=seeded_group["user_id"], role="owner"))
    db_session.add(
        GroupAccessRequirement(
            protected_group_id=seeded_group["group_id"],
            required_group_tg_id=required_group.tg_group_id,
        )
    )
    await db_session.commit()

    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])
    await state.set_state(SettingsFlow.moderation_menu)
    await state.update_data(selected_group=seeded_group["group_id"])

    message = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text=f"🔐 {t('access_gate', 'ar')}",
    )

    await settings_entrypoint(message, state, plugin_manager)

    response = message.log.answers[-1]["text"]
    assert t("access_gate_preview", "ar") in response
    assert t("access_gate_blocked", "ar") in response
    assert t("access_gate_required_groups", "ar", groups="Required Group") in response
    labels = [b.text for row in message.log.answers[-1]["reply_markup"].keyboard for b in row]
    assert f"🌐 {t('language', 'ar')}" in labels
    assert f"🏠 {t('main_menu_btn', 'ar')}" in labels


@pytest.mark.asyncio
async def test_moderation_menu_shows_default_group_settings_status(
    patch_db_dependencies,
    seeded_group,
    fsm_context_factory,
    fake_message_factory,
    plugin_manager,
) -> None:
    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])
    await state.set_state(SettingsFlow.moderation_group)
    await state.update_data(group_items=[{"id": seeded_group["group_id"], "title": "QA Group"}], group_page=1)

    message = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="QA Group",
    )

    await settings_entrypoint(message, state, plugin_manager)

    response = message.log.answers[-1]["text"]
    assert t("group_settings_status", "ar") in response
    assert f"{t('anti_links', 'ar')}: {t('on', 'ar')}" in response
    assert f"{t('anti_spam', 'ar')}: {t('on', 'ar')}" in response
    assert f"{t('anti_ads', 'ar')}: {t('on', 'ar')}" in response
    assert f"{t('anti_spam_mute', 'ar')}: {t('off', 'ar')} (1)" in response
    assert f"{t('anti_ads_mute', 'ar')}: {t('off', 'ar')} (1)" in response
    assert f"{t('warn_auto_remove', 'ar')}: {t('off', 'ar')}" in response
    assert f"{t('anti_bots', 'ar')}: {t('off', 'ar')}" in response
    labels = [b.text for row in message.log.answers[-1]["reply_markup"].keyboard for b in row]
    assert any(label.startswith(f"🔗 {t('anti_links', 'ar')}:") for label in labels)
    assert any(label.startswith(f"🚨 {t('anti_spam', 'ar')}:") for label in labels)
    assert any(label.startswith(f"📣 {t('anti_ads', 'ar')}:") for label in labels)
    assert any(label.startswith(f"🔇 {t('anti_spam_mute', 'ar')}:") for label in labels)
    assert any(label.startswith(f"🔕 {t('anti_ads_mute', 'ar')}:") for label in labels)
    assert any(label.startswith(f"🚪 {t('warn_auto_remove', 'ar')}:") for label in labels)
    assert any(label.startswith(f"🤖 {t('anti_bots', 'ar')}:") for label in labels)
    assert f"🌐 {t('language', 'ar')}" in labels
    assert f"🏠 {t('main_menu_btn', 'ar')}" in labels


@pytest.mark.asyncio
async def test_moderation_menu_toggle_updates_setting_from_reply_keyboard(
    patch_db_dependencies,
    seeded_group,
    db_session,
    fsm_context_factory,
    fake_message_factory,
    plugin_manager,
) -> None:
    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])
    await state.set_state(SettingsFlow.moderation_menu)
    await state.update_data(selected_group=seeded_group["group_id"])

    message = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text=f"🔗 {t('anti_links', 'ar')}: {t('on', 'ar')}",
    )

    await settings_entrypoint(message, state, plugin_manager)

    from bot.services.settings_service import SettingsService

    value = await SettingsService(db_session).get_one(seeded_group["group_id"], "anti_links")
    assert value is False
    assert f"{t('anti_links', 'ar')}: {t('off', 'ar')}" in message.log.answers[-1]["text"]
