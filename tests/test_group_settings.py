from __future__ import annotations

import pytest

from aiogram import Dispatcher
from sqlalchemy import select

from bot.core.event_bus import EventBus
from bot.db.models import GroupSetting
from bot.handlers.menu.settings import apply_slider, open_category, open_group, open_slider, toggle_setting
from bot.services.settings_service import SettingsService


@pytest.mark.asyncio
async def test_toggle_setting_updates_database_and_markup(
    patch_db_dependencies,
    seeded_group,
    db_session,
    fsm_context_factory,
    menu_engine,
    fake_message_factory,
    fake_callback_factory,
    plugin_manager,
) -> None:
    await plugin_manager.load_all(Dispatcher(), EventBus())

    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])
    await state.update_data(selected_group=seeded_group["group_id"], selected_category="moderation")

    host_message = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="toggle",
    )
    callback = fake_callback_factory(
        data="setting:anti_links:toggle",
        from_user_id=seeded_group["user_id"],
        message=host_message,
    )

    await toggle_setting(callback, state, menu_engine, plugin_manager)

    value = await SettingsService(db_session).get_one(seeded_group["group_id"], "anti_links")
    assert value is True
    assert len(host_message.log.edit_markups) == 1


@pytest.mark.asyncio
async def test_slider_setting_updates_numeric_value(
    patch_db_dependencies,
    seeded_group,
    db_session,
    fsm_context_factory,
    menu_engine,
    fake_message_factory,
    fake_callback_factory,
    plugin_manager,
) -> None:
    await plugin_manager.load_all(Dispatcher(), EventBus())
    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])
    await state.update_data(selected_group=seeded_group["group_id"], selected_category="moderation")

    host_message = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="slider",
    )

    open_slider_call = fake_callback_factory(
        data="setting:warn_limit:slider",
        from_user_id=seeded_group["user_id"],
        message=host_message,
    )
    await open_slider(open_slider_call, state, menu_engine, plugin_manager)

    set_slider_call = fake_callback_factory(
        data="slider:warn_limit:8",
        from_user_id=seeded_group["user_id"],
        message=host_message,
    )
    await apply_slider(set_slider_call, state, menu_engine, plugin_manager)

    value = await SettingsService(db_session).get_one(seeded_group["group_id"], "warn_limit")
    assert value == 8
    assert any("Current" in edit["text"] for edit in host_message.log.edits)


@pytest.mark.asyncio
async def test_category_navigation_then_setting_render(
    patch_db_dependencies,
    seeded_group,
    fsm_context_factory,
    menu_engine,
    fake_message_factory,
    fake_callback_factory,
    plugin_manager,
) -> None:
    await plugin_manager.load_all(Dispatcher(), EventBus())

    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])
    host_message = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="nav",
    )

    open_group_call = fake_callback_factory(
        data=f"group:{seeded_group['group_id']}:open",
        from_user_id=seeded_group["user_id"],
        message=host_message,
    )
    await open_group(open_group_call, state, menu_engine, plugin_manager)

    open_category_call = fake_callback_factory(
        data="category:moderation",
        from_user_id=seeded_group["user_id"],
        message=host_message,
    )
    await open_category(open_category_call, state, menu_engine, plugin_manager)

    assert host_message.log.edits[0]["text"] == "Select Category"
    assert host_message.log.edits[1]["text"] == "Moderation"
    labels = [button.text for row in host_message.log.edits[1]["reply_markup"].inline_keyboard for button in row]
    assert any(label.startswith("Anti Links:") for label in labels)
    assert any(label.startswith("Anti-Spam:") for label in labels)
    assert any(label.startswith("Anti Ads:") for label in labels)


@pytest.mark.asyncio
async def test_group_setting_row_created(patch_db_dependencies, seeded_group, db_session) -> None:
    service = SettingsService(db_session)
    await service.set_value(seeded_group["group_id"], "anti_links", False)

    row = (
        await db_session.execute(
            select(GroupSetting).where(
                GroupSetting.group_id == seeded_group["group_id"],
                GroupSetting.key == "anti_links",
            )
        )
    ).scalar_one()
    assert row.value["value"] is False
