from __future__ import annotations

import pytest
from sqlalchemy import select

from bot.db.models import ModerationLog, Warning
from bot.handlers.menu.settings import moderation_action_confirm, moderation_action_prompt
from bot.services.settings_service import SettingsService


@pytest.mark.asyncio
async def test_warn_confirmation_executes_and_logs(
    patch_db_dependencies,
    seeded_group,
    db_session,
    fsm_context_factory,
    menu_engine,
    fake_message_factory,
    fake_callback_factory,
) -> None:
    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])
    await state.update_data(selected_group=seeded_group["group_id"], moderation_target_user_id=5555)

    host_message = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="mod",
    )

    prompt = fake_callback_factory(data="mod:warn", from_user_id=seeded_group["user_id"], message=host_message)
    await moderation_action_prompt(prompt, state, menu_engine)

    confirm = fake_callback_factory(
        data="confirm:warn:5555",
        from_user_id=seeded_group["user_id"],
        message=host_message,
    )
    await moderation_action_confirm(confirm, state, menu_engine)

    warning = (
        await db_session.execute(
            select(Warning).where(Warning.group_id == seeded_group["group_id"], Warning.user_id == 5555)
        )
    ).scalar_one()
    assert warning.count == 1

    log = (
        await db_session.execute(
            select(ModerationLog).where(ModerationLog.group_id == seeded_group["group_id"], ModerationLog.action == "warn_user")
        )
    ).scalar_one()
    assert log.target_user_id == 5555


@pytest.mark.asyncio
async def test_toggle_anti_links_confirmation_updates_setting_and_logs(
    patch_db_dependencies,
    seeded_group,
    db_session,
    fsm_context_factory,
    menu_engine,
    fake_message_factory,
    fake_callback_factory,
) -> None:
    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])
    await state.update_data(selected_group=seeded_group["group_id"])

    host_message = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="mod",
    )

    prompt = fake_callback_factory(data="mod:anti_links", from_user_id=seeded_group["user_id"], message=host_message)
    await moderation_action_prompt(prompt, state, menu_engine)

    confirm = fake_callback_factory(
        data="confirm:anti_links:0",
        from_user_id=seeded_group["user_id"],
        message=host_message,
    )
    await moderation_action_confirm(confirm, state, menu_engine)

    value = await SettingsService(db_session).get_one(seeded_group["group_id"], "anti_links")
    assert value is True

    log = (
        await db_session.execute(
            select(ModerationLog).where(
                ModerationLog.group_id == seeded_group["group_id"],
                ModerationLog.action == "toggle_anti_links",
            )
        )
    ).scalar_one()
    assert log.admin_user_id == seeded_group["user_id"]


@pytest.mark.asyncio
async def test_toggle_anti_ads_confirmation_updates_setting_and_logs(
    patch_db_dependencies,
    seeded_group,
    db_session,
    fsm_context_factory,
    menu_engine,
    fake_message_factory,
    fake_callback_factory,
) -> None:
    state = fsm_context_factory(user_id=seeded_group["user_id"], chat_id=seeded_group["user_id"])
    await state.update_data(selected_group=seeded_group["group_id"])

    host_message = fake_message_factory(
        chat_id=seeded_group["user_id"],
        chat_type="private",
        user_id=seeded_group["user_id"],
        text="mod",
    )

    prompt = fake_callback_factory(data="mod:anti_ads", from_user_id=seeded_group["user_id"], message=host_message)
    await moderation_action_prompt(prompt, state, menu_engine)

    confirm = fake_callback_factory(
        data="confirm:anti_ads:0",
        from_user_id=seeded_group["user_id"],
        message=host_message,
    )
    await moderation_action_confirm(confirm, state, menu_engine)

    value = await SettingsService(db_session).get_one(seeded_group["group_id"], "anti_ads")
    assert value is True

    log = (
        await db_session.execute(
            select(ModerationLog).where(
                ModerationLog.group_id == seeded_group["group_id"],
                ModerationLog.action == "toggle_anti_ads",
            )
        )
    ).scalar_one()
    assert log.admin_user_id == seeded_group["user_id"]
