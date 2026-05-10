from __future__ import annotations

import asyncio
import json
from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import Message
from sqlalchemy import delete, desc, func, select
import structlog

from bot.agents.auth import AgentTelegramAuthError, AgentTelegramAuthService
from bot.agents.service import AgentAuthStateError, AgentService
from bot.config import get_settings
from bot.core.plugin_manager import PluginManager
from bot.db.models import Agent, Group, GroupAdminRole, GroupSetting, ModerationLog, PluginEnabled, Warning
from bot.db.session import SessionLocal
from bot.handlers.menu.states import SettingsFlow
from bot.keyboards.reply import (
    access_gate_keyboard,
    agent_actions_keyboard,
    agent_list_keyboard,
    agent_jobs_menu_keyboard,
    agent_unlink_confirm_keyboard,
    agents_menu_keyboard,
    analytics_menu_keyboard,
    announcements_menu_keyboard,
    bulk_groups_keyboard,
    categories_keyboard,
    empty_groups_keyboard,
    group_management_menu_keyboard,
    groups_keyboard,
    help_menu_keyboard,
    language_keyboard,
    main_menu_keyboard,
    members_menu_keyboard,
    moderation_menu_keyboard,
    plugins_menu_keyboard,
    settings_keyboard,
    slider_keyboard,
    task_agent_keyboard,
    task_executor_keyboard,
    task_delete_confirm_keyboard,
    task_delete_keyboard,
    task_notify_delivery_mode_keyboard,
    task_group_keyboard,
    task_reply_visibility_keyboard,
    tasks_menu_keyboard,
)
from bot.services.group_service import GroupService, upsert_group
from bot.services.permission_service import PermissionService
from bot.services.access_gate_service import AccessGateService, build_access_gate_notice
from bot.services.moderation_settings_store import ModerationSettingsStore
from bot.services.plugin_service import PluginService
from bot.services.scheduled_message_service import ScheduledMessageService
from bot.services.settings_service import SettingsService
from bot.services.task_service import TaskService
from bot.services.user_service import UserService
from bot.utils.i18n import t
from bot.utils.pagination import Page, paginate
from bot.workers.tasks import schedule_bot_message_delete, schedule_scheduled_announcement

router = Router(name="reply_settings_menu")
logger = structlog.get_logger(__name__)


def get_agent_auth_service() -> AgentTelegramAuthService:
    return AgentTelegramAuthService()


def _fallback_lang(message: Message) -> str:
    return get_settings().default_language


async def _lang(message: Message) -> str:
    fallback = get_settings().default_language
    if message.from_user is None:
        return fallback
    async with SessionLocal() as session:
        return await UserService(session).resolve_language(message.from_user.id, fallback=fallback)


def _normalize_menu_text(value: str) -> str:
    invisible_chars = {
        "\ufe0f",  # variation selector
        "\u200b",  # zero width space
        "\u200c",  # zero width non-joiner
        "\u200d",  # zero width joiner
        "\u200e",  # left-to-right mark
        "\u200f",  # right-to-left mark
        "\u2066",  # left-to-right isolate
        "\u2067",  # right-to-left isolate
        "\u2068",  # first strong isolate
        "\u2069",  # pop directional isolate
    }
    normalized = "".join(ch for ch in value if ch not in invisible_chars)
    return normalized.strip()


def _text(message: Message) -> str:
    return _normalize_menu_text(message.text or "")


def _menu_languages() -> tuple[str, ...]:
    default = get_settings().default_language
    ordered = [default]
    for candidate in ("en", "ar"):
        if candidate not in ordered:
            ordered.append(candidate)
    return tuple(ordered)


def _translated_labels(key: str) -> tuple[str, ...]:
    return tuple(t(key, lang) for lang in _menu_languages())


def _matches_exact(message: Message, key: str, *, icon: str | None = None) -> bool:
    txt = _text(message)
    for label in _translated_labels(key):
        if icon and txt == f"{icon} {label}":
            return True
        if txt == label:
            return True
    return False


def _matches_suffix(message: Message, key: str, *, icon: str | None = None) -> bool:
    txt = _text(message)
    for label in _translated_labels(key):
        if icon and txt == f"{icon} {label}":
            return True
        if txt.endswith(label):
            return True
    return False


def _matches_prefix(message: Message, key: str, *, suffix: str = "") -> bool:
    txt = _text(message)
    return any(txt.startswith(f"{label}{suffix}") for label in _translated_labels(key))


def _is_settings_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "settings", icon="⚙")


def _is_back_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "back", icon="⬅")


def _is_refresh_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "refresh", icon="🔄")


def _is_add_group_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "add_group", icon="➕")


def _is_prev_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "prev", icon="◀")


def _is_next_btn(message: Message, lang: str) -> bool:
    _ = lang
    txt = _text(message)
    return any(txt == f"{label} ▶" or txt.startswith(label) for label in _translated_labels("next"))


def _is_page_label(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_prefix(message, "page", suffix=" ")


def _is_home_tab(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "home")


def _is_main_menu_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "main_menu_btn")


def _is_groups_tab(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_exact(message, "groups", icon="📁")


def _is_group_management_tab(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_exact(message, "group_management", icon="🗂")


def _is_members_tab(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_exact(message, "members", icon="👥")


def _is_moderation_tab(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "moderation_tab")


def _is_plugins_tab(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "plugins_tab")


def _is_analytics_tab(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "analytics_tab") or _matches_suffix(message, "stats")


def _is_language_tab(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "language")


def _is_announcements_tab(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "announcements")


def _is_agents_tab(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "agents")


def _is_help_tab(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "help")


def _is_tasks_tab(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "tasks")


def _is_task_catalog_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "task_catalog")


def _is_task_assignments_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "task_assignments")


def _is_delete_task_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "delete_task")


def _is_add_reply_task_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "add_reply_task")


def _is_add_notify_task_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "add_notify_task")


def _notify_delivery_mode_map(lang: str) -> dict[str, str]:
    _ = lang
    mapping: dict[str, str] = {}
    for candidate_lang in _menu_languages():
        mapping[_normalize_menu_text(f"📝 {t('task_notify_mode_text', candidate_lang)}")] = "text"
        mapping[_normalize_menu_text(f"↪️ {t('task_notify_mode_forward', candidate_lang)}")] = "forward"
        mapping[_normalize_menu_text(f"📋 {t('task_notify_mode_copy', candidate_lang)}")] = "copy"
        mapping[_normalize_menu_text(f"📝↪️ {t('task_notify_mode_text_and_forward', candidate_lang)}")] = "text_and_forward"
        mapping[_normalize_menu_text(f"📝📋 {t('task_notify_mode_text_and_copy', candidate_lang)}")] = "text_and_copy"
    return mapping


def _notify_delivery_mode_requires_text(mode: str) -> bool:
    return mode in {"text", "text_and_forward", "text_and_copy"}


def _is_task_executor_bot_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "task_executor_bot")


def _is_task_executor_agent_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "task_executor_agent")


def _is_task_reply_public_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "task_reply_public")


def _is_task_reply_private_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "task_reply_private")


def _parse_bulk_keywords(raw: str) -> list[str]:
    return [part.strip() for part in raw.replace("\n", ",").split(",") if part.strip()]


def _is_lang_en_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "language_en")


def _is_lang_ar_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "language_ar")


def _is_warnings_summary_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "warnings_summary")


def _is_recent_actions_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "recent_actions")


def _is_access_gate_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "access_gate")


def _is_anti_links_btn(message: Message, lang: str) -> bool:
    _ = lang
    return any(_text(message).startswith(f"🔗 {label}") for label in _translated_labels("anti_links"))


def _is_anti_spam_btn(message: Message, lang: str) -> bool:
    _ = lang
    return any(_text(message).startswith(f"🚨 {label}") for label in _translated_labels("anti_spam"))


def _is_anti_ads_btn(message: Message, lang: str) -> bool:
    _ = lang
    return any(_text(message).startswith(f"📣 {label}") for label in _translated_labels("anti_ads"))


def _is_anti_spam_mute_btn(message: Message, lang: str) -> bool:
    _ = lang
    return any(_text(message).startswith(f"🔇 {label}") for label in _translated_labels("anti_spam_mute"))


def _is_anti_ads_mute_btn(message: Message, lang: str) -> bool:
    _ = lang
    return any(_text(message).startswith(f"🔕 {label}") for label in _translated_labels("anti_ads_mute"))


def _is_warn_auto_remove_btn(message: Message, lang: str) -> bool:
    _ = lang
    return any(_text(message).startswith(f"🚪 {label}") for label in _translated_labels("warn_auto_remove"))


def _is_anti_bots_btn(message: Message, lang: str) -> bool:
    _ = lang
    return any(_text(message).startswith(f"🤖 {label}") for label in _translated_labels("anti_bots"))


def _is_join_request_verify_btn(message: Message, lang: str) -> bool:
    _ = lang
    return any(_text(message).startswith(f"📋 {label}") for label in _translated_labels("join_request_verify"))


def _is_reset_warnings_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "reset_warnings")


def _is_refresh_analytics_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "refresh_analytics")


def _is_clear_required_groups_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "clear_required_groups")


def _is_admin_list_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "admin_list")


def _is_member_list_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "member_list")


def _is_promote_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "promote")


def _is_demote_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "demote")


def _is_search_user_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "search_user")


def _is_schedule_message_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "schedule_message")


def _is_view_scheduled_messages_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "view_scheduled_messages")


def _is_edit_scheduled_message_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "edit_scheduled_message")


def _is_delete_scheduled_message_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "delete_scheduled_message")


def _is_send_due_messages_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "send_due_messages")


def _is_select_bulk_groups_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "select_bulk_groups")


def _is_send_bulk_message_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "send_bulk_message")


def _is_link_account_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "link_account")


def _is_my_agents_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "my_agents")


def _is_agent_jobs_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "agent_jobs")


def _is_create_job_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "create_job")


def _is_unlink_account_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "unlink_account")


def _is_confirm_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "confirm")


def _is_clear_selected_groups_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "clear_selected_groups")


def _is_help_overview_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "help_overview")


def _is_help_commands_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "help_commands")


def _is_help_panels_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "help_panels")


def _is_help_announcements_btn(message: Message, lang: str) -> bool:
    _ = lang
    return _matches_suffix(message, "help_announcements")


def _build_access_gate_display_map(candidates: list[dict], selected_tg_group_ids: set[int]) -> dict[str, int]:
    display_map: dict[str, int] = {}
    for group in candidates:
        tg_id = int(group["tg_group_id"])
        mark = "✅" if tg_id in selected_tg_group_ids else "☑"
        display_map[f"{mark} {group['title']}"] = tg_id
    return display_map


def _access_gate_menu_text(lang: str, candidates: list[dict], selected_tg_group_ids: set[int]) -> str:
    selected_titles = [
        str(group["title"])
        for group in candidates
        if int(group["tg_group_id"]) in selected_tg_group_ids
    ]
    preview = build_access_gate_notice(lang, selected_titles)
    return f"{t('access_gate_help', lang)}\n\n{t('access_gate_preview', lang)}\n{preview}"


async def _open_group_selector(
    message: Message,
    state: FSMContext,
    target_state: State,
    page: int,
    title_key: str,
    hide_other_buttons: bool = False,
    empty_title_key: str = "no_groups_found",
) -> None:
    lang = await _lang(message)
    async with SessionLocal() as session:
        groups_page = await GroupService(session).list_admin_groups(message.from_user.id, page=page, page_size=10)

    await state.set_state(target_state)
    await state.update_data(group_page=page, group_items=groups_page.items)

    if groups_page.total == 0:
        await message.answer(
            t(empty_title_key, lang),
            reply_markup=empty_groups_keyboard(lang, include_tabs=not hide_other_buttons),
        )
        return

    await message.answer(
        t(title_key, lang),
        reply_markup=groups_keyboard(groups_page, lang, include_tabs=not hide_other_buttons),
    )


async def _open_groups(message: Message, state: FSMContext, page: int = 1) -> None:
    await _open_group_selector(
        message,
        state,
        SettingsFlow.selecting_group,
        page,
        "select_group",
        hide_other_buttons=True,
        empty_title_key="select_group",
    )


async def _refresh_group_selector(
    message: Message,
    state: FSMContext,
    *,
    page: int,
    target_state: State,
    title_key: str,
    hide_other_buttons: bool,
) -> None:
    lang = await _lang(message)
    async with SessionLocal() as session:
        refreshed = await GroupService(session).refresh_admin_groups(
            user_id=message.from_user.id,
            bot=message.bot,
            fallback_actor=message.from_user,
        )

    await _open_group_selector(
        message,
        state,
        target_state,
        page,
        title_key,
        hide_other_buttons=hide_other_buttons,
    )
    await message.answer(
        t("groups_refreshed", lang, count=refreshed),
        reply_markup=empty_groups_keyboard(lang, include_tabs=not hide_other_buttons)
        if refreshed == 0
        else None,
    )


async def _open_categories(message: Message, state: FSMContext, plugin_manager: PluginManager, group_id: int) -> None:
    lang = await _lang(message)
    schema = plugin_manager.get_settings_schema()
    categories = sorted({entry.category for entry in schema.values()})
    category_map = {t(key, lang): key for key in categories}

    await state.set_state(SettingsFlow.selecting_category)
    await state.update_data(selected_group=group_id, category_map=category_map)
    await message.answer(t("select_category", lang), reply_markup=categories_keyboard(categories, lang, include_tabs=False))


async def _open_category_settings(
    message: Message,
    state: FSMContext,
    plugin_manager: PluginManager,
    group_id: int,
    category: str,
) -> None:
    lang = await _lang(message)
    schema = plugin_manager.get_settings_schema()
    schemas = [item for item in schema.values() if item.category == category]

    async with SessionLocal() as session:
        values = await SettingsService(session).get_all(group_id)

    keyboard, mapping = settings_keyboard(schemas, values, lang, include_tabs=False)
    await state.set_state(SettingsFlow.editing_setting)
    await state.update_data(selected_group=group_id, selected_category=category, setting_map=mapping)
    await message.answer(t(category, lang), reply_markup=keyboard)


async def _moderation_summary_text(group_id: int, lang: str) -> str:
    async with SessionLocal() as session:
        total_warnings = (
            await session.execute(select(func.coalesce(func.sum(Warning.count), 0)).where(Warning.group_id == group_id))
        ).scalar_one()
        warned_users = (
            await session.execute(select(func.count(func.distinct(Warning.user_id))).where(Warning.group_id == group_id))
        ).scalar_one()
        actions = (
            await session.execute(select(func.count(ModerationLog.id)).where(ModerationLog.group_id == group_id))
        ).scalar_one()
        moderation_settings = await ModerationSettingsStore(session).get_settings(group_id)

    def _state(value: bool | int | str | None, default: bool = True) -> str:
        enabled = default if value is None else bool(value)
        return t("on", lang) if enabled else t("off", lang)

    return (
        f"{t('warnings_summary', lang)}\n\n"
        f"- {t('total_warnings', lang)}: {int(total_warnings)}\n"
        f"- {t('warned_users', lang)}: {int(warned_users)}\n"
        f"- {t('total_actions', lang)}: {int(actions)}\n\n"
        f"{t('group_settings_status', lang)}\n"
        f"- {t('anti_links', lang)}: {_state(moderation_settings.anti_links)}\n"
        f"- {t('anti_spam', lang)}: {_state(moderation_settings.anti_spam)}\n"
        f"- {t('anti_ads', lang)}: {_state(moderation_settings.anti_ads)}\n"
        f"- {t('anti_spam_mute', lang)}: {_state(moderation_settings.anti_spam_mute, default=False)}"
        f" ({moderation_settings.anti_spam_mute_limit})\n"
        f"- {t('anti_ads_mute', lang)}: {_state(moderation_settings.anti_ads_mute, default=False)}"
        f" ({moderation_settings.anti_ads_mute_limit})\n"
        f"- {t('warn_auto_remove', lang)}: {_state(moderation_settings.warn_auto_remove, default=False)}"
        f" ({moderation_settings.warn_remove_limit})\n"
        f"- {t('anti_bots', lang)}: {_state(moderation_settings.anti_bots, default=False)}\n"
        f"- {t('join_request_verify', lang)}: {_state(moderation_settings.join_request_verify, default=False)}"
    )


async def _moderation_toggle_states(group_id: int) -> dict[str, bool]:
    async with SessionLocal() as session:
        moderation_settings = await ModerationSettingsStore(session).get_settings(group_id)
    return {
        "anti_links": moderation_settings.anti_links,
        "anti_spam": moderation_settings.anti_spam,
        "anti_ads": moderation_settings.anti_ads,
        "anti_spam_mute": moderation_settings.anti_spam_mute,
        "anti_ads_mute": moderation_settings.anti_ads_mute,
        "warn_auto_remove": moderation_settings.warn_auto_remove,
        "anti_bots": moderation_settings.anti_bots,
        "join_request_verify": moderation_settings.join_request_verify,
    }


async def _recent_actions_text(group_id: int, lang: str) -> str:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(ModerationLog.action, ModerationLog.reason, ModerationLog.created_at)
                .where(ModerationLog.group_id == group_id)
                .order_by(desc(ModerationLog.created_at))
                .limit(5)
            )
        ).all()

    if not rows:
        return t("no_recent_actions", lang)

    lines = [t("recent_actions", lang)]
    for row in rows:
        created = row.created_at.strftime("%Y-%m-%d %H:%M") if row.created_at else "-"
        reason = row.reason or "-"
        lines.append(f"- {created} | {row.action} | {reason}")
    return "\n".join(lines)


async def _open_moderation_menu(message: Message, state: FSMContext, group_id: int) -> None:
    lang = await _lang(message)
    await state.set_state(SettingsFlow.moderation_menu)
    await state.update_data(selected_group=group_id)
    text = await _moderation_summary_text(group_id, lang)
    toggle_states = await _moderation_toggle_states(group_id)
    await message.answer(text, reply_markup=moderation_menu_keyboard(lang, include_tabs=False, toggle_states=toggle_states))


async def _open_members_menu(message: Message, state: FSMContext, group_id: int) -> None:
    lang = await _lang(message)
    await state.set_state(SettingsFlow.members_menu)
    await state.update_data(selected_group=group_id)
    await message.answer(
        f"{t('members', lang)}\n\n{t('members_actions_help', lang)}",
        reply_markup=members_menu_keyboard(lang, include_tabs=False),
    )


async def _open_group_management_menu(message: Message, state: FSMContext) -> None:
    lang = await _lang(message)
    await state.set_state(SettingsFlow.group_management_menu)
    await message.answer(
        f"{t('group_management', lang)}\n\n{t('group_management_help', lang)}",
        reply_markup=group_management_menu_keyboard(lang, include_tabs=False),
    )


async def _open_tasks_menu(message: Message, state: FSMContext) -> None:
    lang = await _lang(message)
    data = await state.get_data()
    group_id = int(data["selected_group"])
    group = await _selected_group(group_id)
    executor_type = str(data.get("task_executor_type") or "bot")
    executor_label = t("task_executor_bot", lang) if executor_type == "bot" else t("task_executor_agent", lang)
    if executor_type == "agent":
        agent_map: dict[str, int] = data.get("task_agent_map", {})
        agent_id = data.get("task_agent_id")
        for label, mapped_id in agent_map.items():
            if mapped_id == agent_id:
                executor_label = label.replace("👤 ", "", 1)
                break
    await state.set_state(SettingsFlow.tasks_menu)
    await message.answer(
        f"{t('tasks', lang)}\n\n{group.title if group else '-'}\n{executor_label}\n\n{t('tasks_panel_help', lang)}",
        reply_markup=tasks_menu_keyboard(lang, include_tabs=False),
    )


def _task_service(session) -> TaskService:
    return TaskService(session, dispatch_agent_job=lambda _job_id: None, dispatch_follow_up=None)


async def _task_catalog_text(lang: str) -> str:
    async with SessionLocal() as session:
        catalog = await _task_service(session).list_catalog()
    lines = [t("task_catalog", lang)]
    for task in catalog:
        lines.append(f"- {task['title']} | {task['trigger']}")
        lines.append(f"  {task['description']}")
    return "\n".join(lines)


async def _task_assignments_text(actor_user_id: int, group_id: int, lang: str) -> str:
    group = await _selected_group(group_id)
    async with SessionLocal() as session:
        assignments = await _task_service(session).list_assignments(actor_user_id=actor_user_id, group_id=group_id)
    if not assignments:
        return f"{t('task_assignments', lang)}\n\n{group.title if group else '-'}\n\n{t('no_tasks_configured', lang)}"

    lines = [t("task_assignments", lang), "", group.title if group else "-"]
    async with SessionLocal() as session:
        agents = await AgentService(session).list_all_active_agents(actor_user_id=actor_user_id)
    agent_names = {int(agent.id): agent.external_account_id for agent in agents}
    for assignment in assignments:
        keyword = str((assignment.get("conditions") or {}).get("text_contains") or "any")
        config = dict(assignment.get("config") or {})
        template = str(config.get("message_template") or config.get("ack_template") or "-")
        if assignment["task_key"] == "notify_destination":
            template = f"{template} -> {config.get('destination') or '-'}"
        executor = assignment["executor_type"]
        if executor == "agent" and assignment.get("agent_id") is not None:
            executor = f"agent:{agent_names.get(int(assignment['agent_id']), assignment['agent_id'])}"
        lines.append(f"- {assignment['task_key']} | {executor} | {keyword} -> {template}")
    return "\n".join(lines)


async def _task_delete_display_map(actor_user_id: int, group_id: int) -> dict[str, str]:
    async with SessionLocal() as session:
        assignments = await _task_service(session).list_assignments(actor_user_id=actor_user_id, group_id=group_id)
        agents = await AgentService(session).list_all_active_agents(actor_user_id=actor_user_id)
    agent_names = {int(agent.id): agent.external_account_id for agent in agents}
    display_map: dict[str, str] = {}
    for assignment in assignments:
        keyword = str((assignment.get("conditions") or {}).get("text_contains") or "any")
        executor = assignment["executor_type"]
        if executor == "agent" and assignment.get("agent_id") is not None:
            executor = f"agent:{agent_names.get(int(assignment['agent_id']), assignment['agent_id'])}"
        label = f"🗑 {assignment['task_key']} | {executor} | {keyword}"
        if label in display_map:
            label = f"{label} | {assignment['assignment_id'][:6]}"
        display_map[label] = str(assignment["assignment_id"])
    return display_map


async def _task_delete_summary(actor_user_id: int, group_id: int, assignment_id: str, lang: str) -> str:
    async with SessionLocal() as session:
        assignments = await _task_service(session).list_assignments(actor_user_id=actor_user_id, group_id=group_id)
    match = next((assignment for assignment in assignments if assignment["assignment_id"] == assignment_id), None)
    if match is None:
        return t("task_delete_confirm", lang)
    keyword = str((match.get("conditions") or {}).get("text_contains") or "any")
    return f"{match['task_key']} | {match['executor_type']} | {keyword}\n\n{t('task_delete_confirm', lang)}"


async def _active_agent_display_map(actor_user_id: int, group_id: int) -> dict[str, int]:
    async with SessionLocal() as session:
        agents = await AgentService(session).list_agents(actor_user_id=actor_user_id, group_id=group_id)
    display_map: dict[str, int] = {}
    for agent in agents:
        if agent.auth_state != "active":
            continue
        display_map[f"👤 {agent.external_account_id}"] = int(agent.id)
    return display_map


async def _all_active_agent_display_map(actor_user_id: int) -> dict[str, int]:
    async with SessionLocal() as session:
        agents = await AgentService(session).list_all_active_agents(actor_user_id=actor_user_id)
    return {f"👤 {agent.external_account_id}": int(agent.id) for agent in agents}


async def _agent_task_group_display_map(actor_user_id: int, agent_id: int) -> dict[str, int]:
    async with SessionLocal() as session:
        groups = await AgentService(session).list_managed_member_groups(actor_user_id=actor_user_id, agent_id=agent_id)
    return {
        str(group["title"]): {
            "group_id": int(group["id"]) if group.get("id") is not None else None,
            "tg_group_id": int(group["tg_group_id"]),
            "title": str(group["title"]),
        }
        for group in groups
    }


async def _bot_task_group_display_map() -> dict[str, dict[str, int | str | None]]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(Group.id, Group.tg_group_id, Group.title)
                .where(Group.is_active.is_(True))
                .order_by(Group.title.asc(), Group.id.asc())
            )
        ).all()
    return {
        str(row.title): {
            "group_id": int(row.id),
            "tg_group_id": int(row.tg_group_id),
            "title": str(row.title),
        }
        for row in rows
    }


async def _toggle_group_setting(group_id: int, key: str, default: bool) -> None:
    async with SessionLocal() as session:
        settings_service = SettingsService(session)
        current = await settings_service.get_one(group_id, key)
        next_value = (not default) if current is None else (not bool(current))
        await settings_service.set_value(group_id, key, next_value)


async def _selected_group(group_id: int) -> Group | None:
    async with SessionLocal() as session:
        return (await session.execute(select(Group).where(Group.id == group_id))).scalar_one_or_none()


def _display_name(user: object) -> str:
    username = getattr(user, "username", None)
    full_name = getattr(user, "full_name", None) or getattr(user, "first_name", None) or "Unknown"
    if username:
        return f"{full_name} (@{username})"
    return str(full_name)


async def _admin_list_text(message: Message, group_id: int, lang: str) -> str:
    group = await _selected_group(group_id)
    if not group:
        return t("unknown_action", lang)

    try:
        admins = await message.bot.get_chat_administrators(group.tg_group_id)
    except Exception:
        return t("members_lookup_failed", lang)

    if not admins:
        return f"{t('admin_list', lang)}\n\n{group.title}\n\n{t('no_admins_found', lang)}"

    lines = [f"{t('admin_list', lang)}", "", group.title]
    for admin in admins:
        status = str(getattr(admin, "status", "")).replace("_", " ").title()
        user = getattr(admin, "user", None)
        lines.append(f"- {_display_name(user)} [{status}]")
    return "\n".join(lines)


_TASK_GROUPS_PAGE_SIZE = 10


def _task_group_page(group_map: dict[str, dict[str, int | str | None]], page: int) -> Page[str]:
    return paginate(list(group_map.keys()), page=page, page_size=_TASK_GROUPS_PAGE_SIZE)


async def _open_task_group_selection(message: Message, state: FSMContext, group_map: dict[str, dict[str, int | str | None]], *, page: int = 1) -> None:
    lang = await _lang(message)
    paged_groups = _task_group_page(group_map, page)
    await state.set_state(SettingsFlow.task_target_group_input)
    await state.update_data(task_group_map=group_map, task_group_page=paged_groups.page)
    await message.answer(
        t("task_group_prompt", lang),
        reply_markup=task_group_keyboard(paged_groups, lang, include_tabs=False),
    )


async def _member_list_text(message: Message, group_id: int, lang: str) -> str:
    group = await _selected_group(group_id)
    if not group:
        return t("unknown_action", lang)

    try:
        admins = await message.bot.get_chat_administrators(group.tg_group_id)
        member_count = await message.bot.get_chat_member_count(group.tg_group_id)
    except Exception:
        return t("members_lookup_failed", lang)

    return (
        f"{t('member_list', lang)}\n\n"
        f"{group.title}\n"
        f"- {t('total_members', lang)}: {member_count}\n"
        f"- {t('total_admins', lang)}: {len(admins)}\n"
        f"{t('member_list_unavailable', lang)}"
    )


def _parse_target_user_id(value: str) -> int | None:
    try:
        return int(value.strip())
    except (TypeError, ValueError):
        return None


async def _member_action_group_tg_id(group_id: int) -> int | None:
    group = await _selected_group(group_id)
    return None if not group else int(group.tg_group_id)


async def _search_member_text(message: Message, group_id: int, target_user_id: int, lang: str) -> str:
    tg_group_id = await _member_action_group_tg_id(group_id)
    group = await _selected_group(group_id)
    if tg_group_id is None or group is None:
        return t("unknown_action", lang)

    try:
        member = await message.bot.get_chat_member(tg_group_id, target_user_id)
    except Exception:
        return t("members_lookup_failed", lang)

    lines = [
        t("members_search_result", lang),
        "",
        group.title,
        f"- ID: {target_user_id}",
        f"- {t('member_status', lang)}: {getattr(member, 'status', '-')}",
    ]
    user = getattr(member, "user", None)
    if user is not None:
        lines.append(f"- {t('member_name', lang)}: {getattr(user, 'full_name', 'Unknown')}")
        username = getattr(user, "username", None)
        if username:
            lines.append(f"- {t('member_username', lang)}: @{username}")
    return "\n".join(lines)


async def _set_member_role(message: Message, group_id: int, target_user_id: int, action: str, lang: str) -> str:
    tg_group_id = await _member_action_group_tg_id(group_id)
    if tg_group_id is None:
        return t("unknown_action", lang)

    promote_payload = {
        "can_manage_chat": action == "promote",
        "can_delete_messages": action == "promote",
        "can_restrict_members": action == "promote",
        "can_invite_users": action == "promote",
        "can_pin_messages": action == "promote",
        "can_manage_video_chats": False,
        "can_promote_members": False,
        "can_change_info": False,
        "can_post_stories": False,
        "can_edit_stories": False,
        "can_delete_stories": False,
        "is_anonymous": False,
    }
    try:
        await message.bot.promote_chat_member(tg_group_id, target_user_id, **promote_payload)
    except Exception:
        return t("members_lookup_failed", lang)

    async with SessionLocal() as session:
        session.add(
            ModerationLog(
                group_id=group_id,
                action=f"{action}_member",
                target_user_id=target_user_id,
                admin_user_id=message.from_user.id if message.from_user else None,
                reason="members_panel",
                details={"source": "reply_keyboard"},
            )
        )
        await session.commit()

    return t("member_promoted" if action == "promote" else "member_demoted", lang)


def _parse_cron_field(field: str, *, minimum: int, maximum: int, sunday_alias: bool = False) -> set[int] | None:
    values: set[int] = set()

    def normalize(token: str) -> int | None:
        if not token.isdigit():
            return None
        value = int(token)
        if sunday_alias and value == 7:
            value = 0
        if value < minimum or value > maximum:
            return None
        return value

    for part in field.split(","):
        part = part.strip()
        if not part:
            return None

        step = 1
        base = part
        if "/" in part:
            base, step_text = part.split("/", 1)
            if not step_text.isdigit() or int(step_text) <= 0:
                return None
            step = int(step_text)

        if base == "*":
            start, end = minimum, maximum
        elif "-" in base:
            start_text, end_text = base.split("-", 1)
            start = normalize(start_text)
            end = normalize(end_text)
            if start is None or end is None or start > end:
                return None
        else:
            value = normalize(base)
            if value is None:
                return None
            start, end = value, value

        values.update(range(start, end + 1, step))

    return values


def _parse_schedule_time(raw: str) -> tuple[datetime, str | None] | None:
    return ScheduledMessageService.parse_schedule_time(raw)


def _parse_delete_after_seconds(raw: str) -> int | None:
    value = raw.strip().lower()
    if value in {"", "0", "skip", "none"}:
        return 0
    if value.isdigit():
        return int(value)
    return None


async def _announcement_entries(group_id: int) -> list[dict]:
    async with SessionLocal() as session:
        return await ScheduledMessageService(session).list_entries(group_id=group_id)


async def _save_announcement_entries(group_id: int, entries: list[dict]) -> None:
    async with SessionLocal() as session:
        normalized = [entry for entry in entries if isinstance(entry, dict)]
        await SettingsService(session).set_value(group_id, "announcement_schedules", normalized)


async def _dispatch_scheduled_message(bot, group_id: int, entry_id: str) -> None:
    entries = await _announcement_entries(group_id)
    entry = next((item for item in entries if item.get("id") == entry_id), None)
    if not entry or entry.get("status") == "sent":
        return

    send_at = datetime.fromisoformat(entry["send_at"])
    delay = max(0.0, (send_at - datetime.utcnow()).total_seconds())
    if delay:
        await asyncio.sleep(delay)

    group = await _selected_group(group_id)
    if not group:
        return
    await bot.send_message(group.tg_group_id, entry["text"])
    async with SessionLocal() as session:
        updated = await ScheduledMessageService(session).mark_delivered(group_id=group_id, entry_id=entry_id)
    if updated and updated.get("cron"):
        _schedule_announcement_task(bot, group_id, entry_id)


def _schedule_announcement_task(bot, group_id: int, entry_id: str) -> None:
    _ = bot

    async def _dispatch() -> None:
        async with SessionLocal() as session:
            entry = await ScheduledMessageService(session).get_entry(group_id=group_id, entry_id=entry_id)
        if entry is None:
            return
        delay_seconds = max(0, int((datetime.fromisoformat(entry["send_at"]) - datetime.utcnow()).total_seconds()))
        schedule_scheduled_announcement(delay_seconds=delay_seconds, group_id=group_id, entry_id=entry_id)

    asyncio.create_task(_dispatch())


async def _scheduled_messages_text(group_id: int, lang: str) -> str:
    group = await _selected_group(group_id)
    entries = await _announcement_entries(group_id)
    if group is None:
        return t("unknown_action", lang)
    if not entries:
        return f"{t('announcement_schedule_list', lang)}\n\n{group.title}\n\n{t('announcement_schedule_none', lang)}"

    lines = [t("announcement_schedule_list", lang), "", group.title]
    for entry in entries:
        status = entry.get("status", "pending")
        delete_after = int(entry.get("delete_after_seconds") or 0)
        suffix = f" | delete:{delete_after}s" if delete_after > 0 else ""
        lines.append(f"- {entry['send_at']} | {status}{suffix} | {entry['text']}")
    return "\n".join(lines)


async def _announcement_display_map(group_id: int) -> dict[str, str]:
    entries = await _announcement_entries(group_id)
    display_map: dict[str, str] = {}
    for entry in entries:
        label = f"🗓 {entry['send_at']} | {str(entry.get('text') or '')[:24]}"
        if label in display_map:
            label = f"{label} | {str(entry['id'])[:6]}"
        display_map[label] = str(entry["id"])
    return display_map


async def _announcement_summary(group_id: int, entry_id: str, lang: str, *, delete_mode: bool = False) -> str:
    entries = await _announcement_entries(group_id)
    entry = next((item for item in entries if str(item.get("id")) == entry_id), None)
    if entry is None:
        return t("announcement_delete_confirm" if delete_mode else "announcement_edit_prompt", lang)
    delete_after = int(entry.get("delete_after_seconds") or 0)
    summary = (
        f"{entry['send_at']} | {entry.get('status', 'pending')}\n"
        f"{entry['text']}\n"
        f"delete_after={delete_after}s"
    )
    confirm = t("announcement_delete_confirm" if delete_mode else "announcement_edit_prompt", lang)
    return f"{summary}\n\n{confirm}"


async def _send_due_announcements(message: Message, group_id: int) -> int:
    entries = await _announcement_entries(group_id)
    group = await _selected_group(group_id)
    if group is None:
        return 0

    sent = 0
    updated: list[dict] = []
    now = datetime.utcnow()
    for entry in entries:
        if entry.get("status") != "sent" and datetime.fromisoformat(entry["send_at"]) <= now:
            sent_message = await message.bot.send_message(group.tg_group_id, entry["text"])
            delete_after_seconds = int(entry.get("delete_after_seconds") or 0)
            message_id = getattr(sent_message, "message_id", None)
            if delete_after_seconds > 0 and message_id is not None:
                schedule_bot_message_delete(
                    delay_seconds=delete_after_seconds,
                    chat_id=group.tg_group_id,
                    message_id=message_id,
                )
            async with SessionLocal() as session:
                saved_entry = await ScheduledMessageService(session).mark_delivered(
                    group_id=group_id,
                    entry_id=str(entry["id"]),
                    delivered_at=now,
                )
            if saved_entry is not None:
                updated.append(saved_entry)
                if saved_entry.get("cron"):
                    _schedule_announcement_task(message.bot, group_id, str(entry["id"]))
            sent += 1
        else:
            updated.append(entry)
    await _save_announcement_entries(group_id, updated)
    return sent


def _build_bulk_display_map(groups: list[dict], selected_group_ids: set[int]) -> dict[str, int]:
    return {
        f"{'✅' if int(group['id']) in selected_group_ids else '☑'} {group['title']}": int(group["id"])
        for group in groups
    }


async def _open_announcements_menu(message: Message, state: FSMContext, group_id: int) -> None:
    lang = await _lang(message)
    await state.set_state(SettingsFlow.announcements_menu)
    await state.update_data(selected_group=group_id, announcement_bulk_groups=[group_id])
    await message.answer(
        f"{t('announcements', lang)}\n\n{t('announcements_panel_help', lang)}",
        reply_markup=announcements_menu_keyboard(lang, include_tabs=False),
    )


async def _agents_for_group(actor_user_id: int, group_id: int) -> list[Agent]:
    async with SessionLocal() as session:
        return await AgentService(session).list_agents(actor_user_id=actor_user_id, group_id=group_id)


async def _resolve_agents_group_id(state: FSMContext, actor_user_id: int) -> int | None:
    data = await state.get_data()
    selected_group = data.get("selected_group")
    async with SessionLocal() as session:
        if selected_group is not None:
            can_manage = await PermissionService(session).can(int(selected_group), actor_user_id, "group.settings.update")
            if can_manage:
                return int(selected_group)
        groups = await GroupService(session).list_admin_groups(actor_user_id, page=1, page_size=1)
    if not groups.items:
        return None
    group_id = int(groups.items[0]["id"])
    await state.update_data(selected_group=group_id)
    return group_id


async def _agents_panel_text(actor_user_id: int, group_id: int, lang: str) -> str:
    agents = await _agents_for_group(actor_user_id, group_id)
    count = len(agents)
    if count == 0:
        return f"{t('agents', lang)}\n\n{t('agents_panel_help', lang)}\n\n{t('no_linked_accounts', lang)}"
    return f"{t('agents', lang)}\n\n{t('agents_panel_help', lang)}\n\n{t('agent_list_title', lang)}: {count}"


async def _agents_list_text(actor_user_id: int, group_id: int, lang: str) -> str:
    agents = await _agents_for_group(actor_user_id, group_id)
    if not agents:
        return t("no_linked_accounts", lang)
    lines = [t("agent_list_title", lang)]
    for agent in agents:
        lines.append(
            f"- {t('agent_account_id', lang)}: {agent.external_account_id} | "
            f"{t('agent_phone_number', lang)}: {agent.phone_number or '-'} | "
            f"{t('agent_status', lang)}: {agent.status} | "
            f"{t('agent_auth_state', lang)}: {agent.auth_state}"
        )
    return "\n".join(lines)


def _build_agent_display_map(agents: list[Agent], lang: str) -> dict[str, int]:
    display_map: dict[str, int] = {}
    for agent in agents:
        title = agent.external_account_id
        if agent.phone_number and agent.phone_number != title:
            title = f"{title} ({agent.phone_number})"
        marker = "✅" if agent.auth_state == "active" else "🟡"
        display_map[f"{marker} {title}"] = int(agent.id)
    return display_map


async def _open_agents_list_menu(message: Message, state: FSMContext, group_id: int) -> None:
    lang = await _lang(message)
    agents = await _agents_for_group(message.from_user.id, group_id)
    display_map = _build_agent_display_map(agents, lang)
    await state.set_state(SettingsFlow.agents_list_menu)
    await state.update_data(selected_group=group_id, agent_display_map=display_map)
    text = t("no_linked_accounts", lang) if not agents else t("agent_list_title", lang)
    await message.answer(
        text,
        reply_markup=agent_list_keyboard(list(display_map.keys()), lang, include_tabs=False),
    )


def _agent_summary_text(agent: Agent, lang: str) -> str:
    return (
        f"{t('agent_selected_title', lang)}\n\n"
        f"{t('agent_account_id', lang)}: {agent.external_account_id}\n"
        f"{t('agent_phone_number', lang)}: {agent.phone_number or '-'}\n"
        f"{t('agent_status', lang)}: {agent.status}\n"
        f"{t('agent_auth_state', lang)}: {agent.auth_state}\n\n"
        f"{t('agent_actions_help', lang)}"
    )


async def _open_selected_agent_menu(message: Message, state: FSMContext, agent_id: int, group_id: int) -> None:
    lang = await _lang(message)
    async with SessionLocal() as session:
        agent = await AgentService(session).get_agent(agent_id=agent_id)
    if agent is None:
        await _open_agents_list_menu(message, state, group_id)
        return
    await state.set_state(SettingsFlow.agents_selected_menu)
    await state.update_data(selected_group=group_id, selected_agent_id=agent_id)
    await message.answer(_agent_summary_text(agent, lang), reply_markup=agent_actions_keyboard(lang, include_tabs=False))


async def _open_unlink_confirm_menu(message: Message, state: FSMContext, agent_id: int, group_id: int) -> None:
    lang = await _lang(message)
    async with SessionLocal() as session:
        agent = await AgentService(session).get_agent(agent_id=agent_id)
    if agent is None:
        await _open_agents_list_menu(message, state, group_id)
        return
    await state.set_state(SettingsFlow.agents_unlink_confirm)
    await state.update_data(selected_group=group_id, selected_agent_id=agent_id)
    await message.answer(
        f"{_agent_summary_text(agent, lang)}\n\n{t('agent_unlink_confirm', lang)}",
        reply_markup=agent_unlink_confirm_keyboard(lang, include_tabs=False),
    )


async def _agent_jobs_text(actor_user_id: int, group_id: int, lang: str) -> str:
    async with SessionLocal() as session:
        service = AgentService(session)
        jobs = await service.list_jobs(actor_user_id=actor_user_id, group_id=group_id, limit=5)
        agents = {
            agent.id: agent.external_account_id
            for agent in await service.list_agents(actor_user_id=actor_user_id, group_id=group_id)
        }
    if not jobs:
        return t("agent_jobs_empty", lang)
    lines = [t("agent_jobs_overview", lang)]
    for job in jobs:
        lines.append(
            f"- {agents.get(job.agent_id, job.agent_id)} | {job.job_type} | {job.status}"
        )
    return "\n".join(lines)


async def _open_agents_menu(message: Message, state: FSMContext, group_id: int) -> None:
    lang = await _lang(message)
    await state.set_state(SettingsFlow.agents_menu)
    await state.update_data(selected_group=group_id)
    await message.answer(
        await _agents_panel_text(message.from_user.id, group_id, lang),
        reply_markup=agents_menu_keyboard(lang, include_tabs=False),
    )


async def _open_agent_jobs_menu(message: Message, state: FSMContext, group_id: int) -> None:
    lang = await _lang(message)
    await state.set_state(SettingsFlow.agents_jobs_menu)
    await state.update_data(selected_group=group_id)
    await message.answer(
        await _agent_jobs_text(message.from_user.id, group_id, lang),
        reply_markup=agent_jobs_menu_keyboard(lang, include_tabs=False),
    )


def _parse_agent_job_input(value: str) -> tuple[str, str, dict[str, object]] | None:
    parts = [part.strip() for part in value.split("|", maxsplit=2)]
    if len(parts) < 2 or not parts[0] or not parts[1]:
        return None
    account_id = parts[0]
    job_type = parts[1]
    payload: dict[str, object] = {}
    if len(parts) == 3 and parts[2]:
        try:
            raw = json.loads(parts[2])
        except Exception:
            return None
        if not isinstance(raw, dict):
            return None
        payload = raw
    return account_id, job_type, payload


async def _open_bulk_group_selection(message: Message, state: FSMContext, group_id: int) -> None:
    lang = await _lang(message)
    async with SessionLocal() as session:
        groups = await GroupService(session).list_admin_groups_all(message.from_user.id)

    selected = set(int(x) for x in (await state.get_data()).get("announcement_bulk_groups", [group_id]))
    display_map = _build_bulk_display_map(groups, selected)
    await state.set_state(SettingsFlow.announcement_bulk_groups)
    await state.update_data(
        selected_group=group_id,
        announcement_bulk_candidates=groups,
        announcement_bulk_display_map=display_map,
        announcement_bulk_groups=list(selected),
    )
    await message.answer(
        f"{t('announcement_bulk_help', lang)}\n\n{t('announcement_bulk_groups_selected', lang, groups=', '.join(str(g['title']) for g in groups if int(g['id']) in selected))}",
        reply_markup=bulk_groups_keyboard(groups, selected, lang, include_tabs=False),
    )


async def _help_panel_text(lang: str, section: str = "overview") -> str:
    if section == "commands":
        return f"{t('help_commands', lang)}\n\n{t('help_text', lang)}"
    if section == "panels":
        return f"{t('help_panels', lang)}\n\n{t('help_panels_text', lang)}"
    if section == "announcements":
        return f"{t('help_announcements', lang)}\n\n{t('help_announcements_text', lang)}"
    return f"{t('help_panel_intro', lang)}\n\n{t('help_overview_text', lang)}"


async def _open_access_gate_menu(message: Message, state: FSMContext, group_id: int) -> None:
    lang = await _lang(message)
    async with SessionLocal() as session:
        groups = await GroupService(session).list_admin_groups_all(message.from_user.id)
        requirements = await AccessGateService(session).list_required_group_tg_ids(group_id)

    candidates = [g for g in groups if g["id"] != group_id]
    selected = set(requirements)
    display_map = _build_access_gate_display_map(candidates, selected)

    await state.set_state(SettingsFlow.access_gate_menu)
    await state.update_data(
        selected_group=group_id,
        access_gate_display_map=display_map,
        access_gate_candidates=candidates,
        access_gate_selected=list(selected),
    )
    await message.answer(
        _access_gate_menu_text(lang, candidates, selected),
        reply_markup=access_gate_keyboard(candidates, selected, lang, include_tabs=False),
    )


async def _open_plugins_menu(
    message: Message,
    state: FSMContext,
    plugin_manager: PluginManager,
    group_id: int,
) -> None:
    lang = await _lang(message)
    async with SessionLocal() as session:
        service = PluginService(session)
        configured = await service.list_group_plugins(group_id)

    available = {loaded.name: True for loaded in plugin_manager.loaded_plugins()}
    for name, enabled in configured.items():
        available[name] = enabled

    display_map = {f"{'✅' if enabled else '❌'} {name}": name for name, enabled in sorted(available.items())}

    await state.set_state(SettingsFlow.plugins_menu)
    await state.update_data(selected_group=group_id, plugin_display_map=display_map)
    await message.answer(t("plugins_tab", lang), reply_markup=plugins_menu_keyboard(available, lang, include_tabs=False))


async def _analytics_text(group_id: int, lang: str) -> str:
    async with SessionLocal() as session:
        settings_count = (
            await session.execute(select(func.count(GroupSetting.id)).where(GroupSetting.group_id == group_id))
        ).scalar_one()
        enabled_plugins = (
            await session.execute(
                select(func.count(PluginEnabled.id)).where(
                    PluginEnabled.group_id == group_id,
                    PluginEnabled.enabled.is_(True),
                )
            )
        ).scalar_one()
        warnings_total = (
            await session.execute(select(func.coalesce(func.sum(Warning.count), 0)).where(Warning.group_id == group_id))
        ).scalar_one()
        actions_total = (
            await session.execute(select(func.count(ModerationLog.id)).where(ModerationLog.group_id == group_id))
        ).scalar_one()

    return (
        f"{t('analytics_tab', lang)}\n\n"
        f"- {t('configured_settings', lang)}: {int(settings_count)}\n"
        f"- {t('enabled_plugins_count', lang)}: {int(enabled_plugins)}\n"
        f"- {t('total_warnings', lang)}: {int(warnings_total)}\n"
        f"- {t('total_actions', lang)}: {int(actions_total)}"
    )


async def _open_analytics_menu(message: Message, state: FSMContext, group_id: int) -> None:
    lang = await _lang(message)
    await state.set_state(SettingsFlow.analytics_menu)
    await state.update_data(selected_group=group_id)
    text = await _analytics_text(group_id, lang)
    await message.answer(text, reply_markup=analytics_menu_keyboard(lang, include_tabs=False))


async def _select_group_in_state(
    message: Message,
    state: FSMContext,
    target: str,
    plugin_manager: PluginManager,
) -> bool:
    lang = await _lang(message)
    data = await state.get_data()
    page = int(data.get("group_page", 1))
    group_items: list[dict] = data.get("group_items", [])

    if _is_back_btn(message, lang):
        await state.clear()
        await message.answer(
            t("main_menu", lang),
            reply_markup=main_menu_keyboard(lang, dashboard_url=(get_settings().webapp_url or get_settings().dashboard_url)),
        )
        return True
    if _is_refresh_btn(message, lang):
        mapping = {
            "settings": SettingsFlow.selecting_group,
            "moderation": SettingsFlow.moderation_group,
            "members": SettingsFlow.members_group,
            "plugins": SettingsFlow.plugins_group,
            "analytics": SettingsFlow.analytics_group,
            "tasks": SettingsFlow.tasks_group,
            "announcements": SettingsFlow.announcements_group,
            "agents": SettingsFlow.agents_group,
        }
        title_key = {
            "settings": "select_group",
            "moderation": "select_group_for_moderation",
            "members": "select_group_for_members",
            "plugins": "select_group_for_plugins",
            "analytics": "select_group_for_analytics",
            "tasks": "select_group_for_tasks",
            "announcements": "select_group_for_announcements",
            "agents": "select_group_for_agents",
        }
        await _refresh_group_selector(
            message,
            state,
            page=page,
            target_state=mapping[target],
            title_key=title_key[target],
            hide_other_buttons=target in {"settings", "moderation", "members", "analytics", "tasks", "announcements", "agents"},
        )
        return True
    if _is_add_group_btn(message, lang):
        me = await message.bot.get_me()
        await message.answer(f"{t('add_group_help', lang)}\nhttps://t.me/{me.username}?startgroup=true")
        return True
    if _is_prev_btn(message, lang):
        mapping = {
            "settings": SettingsFlow.selecting_group,
            "moderation": SettingsFlow.moderation_group,
            "members": SettingsFlow.members_group,
            "plugins": SettingsFlow.plugins_group,
            "analytics": SettingsFlow.analytics_group,
            "tasks": SettingsFlow.tasks_group,
            "announcements": SettingsFlow.announcements_group,
            "agents": SettingsFlow.agents_group,
        }
        title_key = {
            "settings": "select_group",
            "moderation": "select_group_for_moderation",
            "members": "select_group_for_members",
            "plugins": "select_group_for_plugins",
            "analytics": "select_group_for_analytics",
            "tasks": "select_group_for_tasks",
            "announcements": "select_group_for_announcements",
            "agents": "select_group_for_agents",
        }
        await _open_group_selector(
            message,
            state,
            mapping[target],
            max(1, page - 1),
            title_key[target],
            hide_other_buttons=target in {"settings", "moderation", "members", "analytics", "tasks", "announcements", "agents"},
        )
        return True
    if _is_next_btn(message, lang):
        mapping = {
            "settings": SettingsFlow.selecting_group,
            "moderation": SettingsFlow.moderation_group,
            "members": SettingsFlow.members_group,
            "plugins": SettingsFlow.plugins_group,
            "analytics": SettingsFlow.analytics_group,
            "tasks": SettingsFlow.tasks_group,
            "announcements": SettingsFlow.announcements_group,
            "agents": SettingsFlow.agents_group,
        }
        title_key = {
            "settings": "select_group",
            "moderation": "select_group_for_moderation",
            "members": "select_group_for_members",
            "plugins": "select_group_for_plugins",
            "analytics": "select_group_for_analytics",
            "tasks": "select_group_for_tasks",
            "announcements": "select_group_for_announcements",
            "agents": "select_group_for_agents",
        }
        await _open_group_selector(
            message,
            state,
            mapping[target],
            page + 1,
            title_key[target],
            hide_other_buttons=target in {"settings", "moderation", "members", "analytics", "tasks", "announcements", "agents"},
        )
        return True
    if _is_page_label(message, lang):
        return True

    selected = next((item for item in group_items if item["title"] == _text(message)), None)
    if not selected:
        await message.answer(t("unknown_action", lang))
        return True

    async with SessionLocal() as session:
        can_manage = await PermissionService(session).can(selected["id"], message.from_user.id, "group.settings.update")
    if not can_manage:
        await message.answer(t("permission_denied", lang))
        return True

    if target == "settings":
        await _open_categories(message, state, plugin_manager, selected["id"])
    elif target == "moderation":
        await _open_moderation_menu(message, state, selected["id"])
    elif target == "members":
        await _open_members_menu(message, state, selected["id"])
    elif target == "plugins":
        await _open_plugins_menu(message, state, plugin_manager, selected["id"])
    elif target == "announcements":
        await _open_announcements_menu(message, state, selected["id"])
    elif target == "agents":
        await _open_agents_menu(message, state, selected["id"])
    elif target == "tasks":
        await state.update_data(selected_group=selected["id"])
        await _open_tasks_menu(message, state)
    else:
        await _open_analytics_menu(message, state, selected["id"])
    return True


@router.message(F.chat.type == "private", F.text)
async def settings_entrypoint(message: Message, state: FSMContext, plugin_manager: PluginManager) -> None:
    if message.chat.type != "private":
        return
    lang = await _lang(message)
    text = _text(message)
    current_state = await state.get_state()
    logger.info(
        "private_menu_message_received",
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else None,
        state=current_state,
        text=text,
        raw_text=message.text or "",
        lang=lang,
    )
    logger.info(
        "private_menu_state_snapshot",
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else None,
        state=current_state,
        text=text,
        data=await state.get_data(),
    )

    if _is_settings_btn(message, lang):
        await _open_groups(message, state, page=1)
        logger.info(
            "private_menu_opened_settings_group_selector",
            chat_id=message.chat.id,
            user_id=message.from_user.id if message.from_user else None,
            text=text,
            lang=lang,
            previous_state=current_state,
        )
        return
    if _is_home_tab(message, lang) or _is_main_menu_btn(message, lang):
        await state.clear()
        await message.answer(
            t("main_menu", lang),
            reply_markup=main_menu_keyboard(lang, dashboard_url=(get_settings().webapp_url or get_settings().dashboard_url)),
        )
        return
    if _is_groups_tab(message, lang):
        await _open_groups(message, state, page=1)
        return
    if _is_group_management_tab(message, lang):
        await _open_group_management_menu(message, state)
        return
    if _is_members_tab(message, lang):
        await _open_group_selector(
            message,
            state,
            SettingsFlow.members_group,
            1,
            "select_group_for_members",
            hide_other_buttons=True,
        )
        return
    if _is_moderation_tab(message, lang):
        await _open_group_selector(
            message,
            state,
            SettingsFlow.moderation_group,
            1,
            "select_group_for_moderation",
            hide_other_buttons=True,
        )
        return
    if _is_plugins_tab(message, lang):
        await _open_group_selector(message, state, SettingsFlow.plugins_group, 1, "select_group_for_plugins")
        return
    if _is_analytics_tab(message, lang):
        await _open_group_selector(
            message,
            state,
            SettingsFlow.analytics_group,
            1,
            "select_group_for_analytics",
            hide_other_buttons=True,
        )
        return
    if _is_language_tab(message, lang):
        await state.set_state(SettingsFlow.language_menu)
        await message.answer(t("choose_language", lang), reply_markup=language_keyboard(lang))
        return
    if _is_announcements_tab(message, lang):
        await _open_group_selector(
            message,
            state,
            SettingsFlow.announcements_group,
            1,
            "select_group_for_announcements",
            hide_other_buttons=True,
        )
        return
    if _is_tasks_tab(message, lang):
        await state.set_state(SettingsFlow.tasks_executor_menu)
        await state.update_data(
            selected_group=None,
            task_keyword=None,
            task_executor_type=None,
            task_agent_id=None,
            task_agent_map={},
            task_group_map={},
        )
        await message.answer(
            t("task_executor_prompt", lang),
            reply_markup=task_executor_keyboard(lang, include_tabs=False),
        )
        return
    if _is_agents_tab(message, lang):
        group_id = await _resolve_agents_group_id(state, message.from_user.id)
        if group_id is None:
            await message.answer(
                t("no_groups_found", lang),
                reply_markup=empty_groups_keyboard(lang, include_tabs=False),
            )
            return
        await _open_agents_list_menu(message, state, group_id)
        return
    if _is_help_tab(message, lang):
        await state.set_state(SettingsFlow.help_menu)
        await message.answer(
            await _help_panel_text(lang),
            reply_markup=help_menu_keyboard(lang, include_tabs=False),
        )
        return

    if current_state is None:
        logger.info(
            "private_menu_no_match_in_idle_state",
            chat_id=message.chat.id,
            user_id=message.from_user.id if message.from_user else None,
            text=text,
            lang=lang,
        )
        from bot.handlers.fallback import private_fallback

        await private_fallback(message)
        return

    if current_state == SettingsFlow.selecting_group.state:
        await _select_group_in_state(message, state, "settings", plugin_manager)
        return

    if current_state == SettingsFlow.group_management_menu.state:
        if _is_back_btn(message, lang):
            await state.clear()
            await message.answer(
                t("main_menu", lang),
                reply_markup=main_menu_keyboard(lang, dashboard_url=(get_settings().webapp_url or get_settings().dashboard_url)),
            )
            return
        if _is_moderation_tab(message, lang):
            await _open_group_selector(
                message,
                state,
                SettingsFlow.moderation_group,
                1,
                "select_group_for_moderation",
                hide_other_buttons=True,
            )
            return
        if _is_members_tab(message, lang):
            await _open_group_selector(
                message,
                state,
                SettingsFlow.members_group,
                1,
                "select_group_for_members",
                hide_other_buttons=True,
            )
            return
        if _is_analytics_tab(message, lang):
            await _open_group_selector(
                message,
                state,
                SettingsFlow.analytics_group,
                1,
                "select_group_for_analytics",
                hide_other_buttons=True,
            )
            return
        await _open_group_management_menu(message, state)
        return

    if current_state == SettingsFlow.moderation_group.state:
        await _select_group_in_state(message, state, "moderation", plugin_manager)
        return

    if current_state == SettingsFlow.members_group.state:
        await _select_group_in_state(message, state, "members", plugin_manager)
        return

    if current_state == SettingsFlow.plugins_group.state:
        await _select_group_in_state(message, state, "plugins", plugin_manager)
        return

    if current_state == SettingsFlow.analytics_group.state:
        await _select_group_in_state(message, state, "analytics", plugin_manager)
        return

    if current_state == SettingsFlow.tasks_group.state:
        await _select_group_in_state(message, state, "tasks", plugin_manager)
        return

    if current_state == SettingsFlow.announcements_group.state:
        await _select_group_in_state(message, state, "announcements", plugin_manager)
        return

    if current_state == SettingsFlow.selecting_category.state:
        data = await state.get_data()
        group_id = data["selected_group"]
        category_map: dict[str, str] = data.get("category_map", {})

        if _is_back_btn(message, lang):
            await _open_groups(message, state, page=int(data.get("group_page", 1)))
            return

        category = category_map.get(text)
        if not category:
            await message.answer(t("unknown_action", lang))
            return

        await _open_category_settings(message, state, plugin_manager, group_id, category)
        return

    if current_state == SettingsFlow.editing_setting.state:
        data = await state.get_data()
        group_id = data["selected_group"]
        category = data["selected_category"]
        setting_map: dict[str, tuple[str, str]] = data.get("setting_map", {})

        if _is_back_btn(message, lang):
            await _open_categories(message, state, plugin_manager, group_id)
            return

        setting = setting_map.get(text)
        if not setting:
            if text in {"-1", "+1"}:
                slider_key = data.get("slider_key")
                current_value = int(data.get("slider_value", 0))
                if not slider_key:
                    await message.answer(t("unknown_action", lang))
                    return
                schema = plugin_manager.get_settings_schema()[slider_key]
                next_value = current_value + (1 if text == "+1" else -1)
                if schema.min is not None:
                    next_value = max(schema.min, next_value)
                if schema.max is not None:
                    next_value = min(schema.max, next_value)
                async with SessionLocal() as session:
                    can_manage = await PermissionService(session).can(
                        group_id, message.from_user.id, "group.settings.update"
                    )
                    if not can_manage:
                        await message.answer(t("permission_denied", lang))
                        return
                    await SettingsService(session).set_value(group_id, slider_key, next_value)
                await state.update_data(slider_value=next_value)
                await message.answer(
                    f"{t(schema.label_key, lang)}\n\n{t('current', lang)}: {next_value}",
                    reply_markup=slider_keyboard(lang, include_tabs=False),
                )
                return

            await message.answer(t("unknown_action", lang))
            return

        key, setting_type = setting
        async with SessionLocal() as session:
            can_manage = await PermissionService(session).can(group_id, message.from_user.id, "group.settings.update")
            if not can_manage:
                await message.answer(t("permission_denied", lang))
                return
            service = SettingsService(session)
            if setting_type == "toggle":
                current = await service.get_one(group_id, key)
                await service.set_value(group_id, key, not bool(current))
                await _open_category_settings(message, state, plugin_manager, group_id, category)
                return
            current = await service.get_one(group_id, key)

        schema = plugin_manager.get_settings_schema()[key]
        current_value = int(current if current is not None else schema.default or 0)
        await state.update_data(slider_key=key, slider_value=current_value)
        await message.answer(
            f"{t(schema.label_key, lang)}\n\n{t('current', lang)}: {current_value}",
            reply_markup=slider_keyboard(lang, include_tabs=False),
        )
        return

    if current_state == SettingsFlow.moderation_menu.state:
        data = await state.get_data()
        group_id = data["selected_group"]

        if _is_back_btn(message, lang):
            await _open_group_selector(
                message,
                state,
                SettingsFlow.moderation_group,
                1,
                "select_group_for_moderation",
                hide_other_buttons=True,
            )
            return
        if _is_anti_links_btn(message, lang):
            await _toggle_group_setting(group_id, "anti_links", default=True)
            await _open_moderation_menu(message, state, group_id)
            return
        if _is_anti_spam_btn(message, lang):
            await _toggle_group_setting(group_id, "anti_spam", default=True)
            await _open_moderation_menu(message, state, group_id)
            return
        if _is_anti_ads_btn(message, lang):
            await _toggle_group_setting(group_id, "anti_ads", default=True)
            await _open_moderation_menu(message, state, group_id)
            return
        if _is_anti_spam_mute_btn(message, lang):
            await _toggle_group_setting(group_id, "anti_spam_mute", default=False)
            await _open_moderation_menu(message, state, group_id)
            return
        if _is_anti_ads_mute_btn(message, lang):
            await _toggle_group_setting(group_id, "anti_ads_mute", default=False)
            await _open_moderation_menu(message, state, group_id)
            return
        if _is_warn_auto_remove_btn(message, lang):
            await _toggle_group_setting(group_id, "warn_auto_remove", default=False)
            await _open_moderation_menu(message, state, group_id)
            return
        if _is_anti_bots_btn(message, lang):
            await _toggle_group_setting(group_id, "anti_bots", default=False)
            await _open_moderation_menu(message, state, group_id)
            return
        if _is_join_request_verify_btn(message, lang):
            await _toggle_group_setting(group_id, "join_request_verify", default=False)
            await _open_moderation_menu(message, state, group_id)
            return
        if _is_warnings_summary_btn(message, lang):
            await message.answer(
                await _moderation_summary_text(group_id, lang),
                reply_markup=moderation_menu_keyboard(
                    lang,
                    include_tabs=False,
                    toggle_states=await _moderation_toggle_states(group_id),
                ),
            )
            return
        if _is_recent_actions_btn(message, lang):
            await message.answer(
                await _recent_actions_text(group_id, lang),
                reply_markup=moderation_menu_keyboard(
                    lang,
                    include_tabs=False,
                    toggle_states=await _moderation_toggle_states(group_id),
                ),
            )
            return
        if _is_access_gate_btn(message, lang):
            await _open_access_gate_menu(message, state, group_id)
            return
        if _is_reset_warnings_btn(message, lang):
            async with SessionLocal() as session:
                await session.execute(delete(Warning).where(Warning.group_id == group_id))
                session.add(
                    ModerationLog(
                        group_id=group_id,
                        action="warnings_reset",
                        target_user_id=None,
                        admin_user_id=message.from_user.id,
                        reason="reset_from_keyboard",
                        details={},
                        created_at=datetime.utcnow(),
                    )
                )
                await session.commit()
            await message.answer(
                t("warnings_reset_done", lang),
                reply_markup=moderation_menu_keyboard(
                    lang,
                    include_tabs=False,
                    toggle_states=await _moderation_toggle_states(group_id),
                ),
            )
            return

    if current_state == SettingsFlow.members_menu.state:
        data = await state.get_data()
        group_id = data["selected_group"]

        if _is_back_btn(message, lang):
            await _open_group_selector(
                message,
                state,
                SettingsFlow.members_group,
                1,
                "select_group_for_members",
                hide_other_buttons=True,
            )
            return
        if _is_admin_list_btn(message, lang):
            await message.answer(
                await _admin_list_text(message, group_id, lang),
                reply_markup=members_menu_keyboard(lang, include_tabs=False),
            )
            return
        if _is_member_list_btn(message, lang):
            await message.answer(
                await _member_list_text(message, group_id, lang),
                reply_markup=members_menu_keyboard(lang, include_tabs=False),
            )
            return
        if _is_promote_btn(message, lang) or _is_demote_btn(message, lang) or _is_search_user_btn(message, lang):
            action = "promote" if _is_promote_btn(message, lang) else "demote" if _is_demote_btn(message, lang) else "search"
            await state.set_state(SettingsFlow.members_action_input)
            await state.update_data(selected_group=group_id, members_action=action)
            await message.answer(
                t("members_action_prompt", lang),
                reply_markup=members_menu_keyboard(lang, include_tabs=False),
            )
            return
        await message.answer(
            t("members_actions_help", lang),
            reply_markup=members_menu_keyboard(lang, include_tabs=False),
        )
        return

    if current_state == SettingsFlow.members_action_input.state:
        data = await state.get_data()
        group_id = data["selected_group"]
        action = data.get("members_action", "search")
        if _is_back_btn(message, lang):
            await _open_members_menu(message, state, group_id)
            return

        target_user_id = _parse_target_user_id(text)
        if target_user_id is None:
            await message.answer(
                t("members_action_target_invalid", lang),
                reply_markup=members_menu_keyboard(lang, include_tabs=False),
            )
            return

        if action == "search":
            response = await _search_member_text(message, group_id, target_user_id, lang)
        else:
            response = await _set_member_role(message, group_id, target_user_id, action, lang)
        await state.set_state(SettingsFlow.members_menu)
        await message.answer(response, reply_markup=members_menu_keyboard(lang, include_tabs=False))
        return

    if current_state == SettingsFlow.announcements_menu.state:
        data = await state.get_data()
        group_id = data["selected_group"]

        if _is_back_btn(message, lang):
            await _open_group_selector(
                message,
                state,
                SettingsFlow.announcements_group,
                1,
                "select_group_for_announcements",
                hide_other_buttons=True,
            )
            return
        if _is_schedule_message_btn(message, lang):
            await state.set_state(SettingsFlow.announcement_schedule_text)
            await state.update_data(selected_group=group_id)
            await message.answer(
                t("announcement_schedule_prompt", lang),
                reply_markup=announcements_menu_keyboard(lang, include_tabs=False),
            )
            return
        if _is_view_scheduled_messages_btn(message, lang):
            await message.answer(
                await _scheduled_messages_text(group_id, lang),
                reply_markup=announcements_menu_keyboard(lang, include_tabs=False),
            )
            return
        if _is_edit_scheduled_message_btn(message, lang):
            display_map = await _announcement_display_map(group_id)
            if not display_map:
                await message.answer(
                    t("announcement_schedule_none", lang),
                    reply_markup=announcements_menu_keyboard(lang, include_tabs=False),
                )
                return
            await state.set_state(SettingsFlow.announcement_edit_select)
            await state.update_data(announcement_edit_map=display_map)
            await message.answer(
                t("announcement_edit_prompt", lang),
                reply_markup=task_delete_keyboard(list(display_map.keys()), lang, include_tabs=False),
            )
            return
        if _is_delete_scheduled_message_btn(message, lang):
            display_map = await _announcement_display_map(group_id)
            if not display_map:
                await message.answer(
                    t("announcement_schedule_none", lang),
                    reply_markup=announcements_menu_keyboard(lang, include_tabs=False),
                )
                return
            await state.set_state(SettingsFlow.announcement_delete_select)
            await state.update_data(announcement_delete_map=display_map)
            await message.answer(
                t("announcement_delete_prompt", lang),
                reply_markup=task_delete_keyboard(list(display_map.keys()), lang, include_tabs=False),
            )
            return
        if _is_send_due_messages_btn(message, lang):
            sent = await _send_due_announcements(message, group_id)
            await message.answer(
                t("announcement_due_none" if sent == 0 else "announcement_due_sent", lang, count=sent),
                reply_markup=announcements_menu_keyboard(lang, include_tabs=False),
            )
            return
        if _is_select_bulk_groups_btn(message, lang):
            await _open_bulk_group_selection(message, state, group_id)
            return
        if _is_send_bulk_message_btn(message, lang):
            selected_groups = [int(x) for x in data.get("announcement_bulk_groups", [group_id])]
            if not selected_groups:
                await message.answer(
                    t("announcement_bulk_none_selected", lang),
                    reply_markup=announcements_menu_keyboard(lang, include_tabs=False),
                )
                return
            await state.set_state(SettingsFlow.announcement_bulk_text)
            await state.update_data(selected_group=group_id, announcement_bulk_groups=selected_groups)
            await message.answer(
                t("announcement_bulk_prompt", lang),
                reply_markup=announcements_menu_keyboard(lang, include_tabs=False),
            )
            return
        await message.answer(
            t("announcements_panel_help", lang),
            reply_markup=announcements_menu_keyboard(lang, include_tabs=False),
        )
        return

    if current_state == SettingsFlow.tasks_menu.state:
        data = await state.get_data()
        group_id = int(data["selected_group"])
        if _is_back_btn(message, lang):
            display_map: dict[str, int] = data.get("task_group_map", {})
            await _open_task_group_selection(
                message,
                state,
                display_map,
                page=int(data.get("task_group_page") or 1),
            )
            return
        if _is_add_reply_task_btn(message, lang):
            await state.set_state(SettingsFlow.task_reply_keyword_input)
            await state.update_data(selected_group=group_id)
            await message.answer(
                t("task_keyword_prompt", lang),
                reply_markup=tasks_menu_keyboard(lang, include_tabs=False),
            )
            return
        if _is_add_notify_task_btn(message, lang):
            await state.set_state(SettingsFlow.task_notify_keyword_input)
            await state.update_data(selected_group=group_id)
            await message.answer(
                t("task_notify_keyword_prompt", lang),
                reply_markup=tasks_menu_keyboard(lang, include_tabs=False),
            )
            return
        if _is_task_catalog_btn(message, lang):
            await message.answer(
                await _task_catalog_text(lang),
                reply_markup=tasks_menu_keyboard(lang, include_tabs=False),
            )
            return
        if _is_task_assignments_btn(message, lang):
            await message.answer(
                await _task_assignments_text(message.from_user.id, group_id, lang),
                reply_markup=tasks_menu_keyboard(lang, include_tabs=False),
            )
            return
        if _is_delete_task_btn(message, lang):
            display_map = await _task_delete_display_map(message.from_user.id, group_id)
            if not display_map:
                await message.answer(
                    t("no_tasks_configured", lang),
                    reply_markup=tasks_menu_keyboard(lang, include_tabs=False),
                )
                return
            await state.set_state(SettingsFlow.task_delete_select)
            await state.update_data(task_delete_map=display_map)
            await message.answer(
                t("task_delete_prompt", lang),
                reply_markup=task_delete_keyboard(list(display_map.keys()), lang, include_tabs=False),
            )
            return
        await _open_tasks_menu(message, state)
        return

    if current_state == SettingsFlow.task_delete_select.state:
        data = await state.get_data()
        group_id = int(data["selected_group"])
        display_map: dict[str, str] = data.get("task_delete_map", {})
        if _is_back_btn(message, lang):
            await _open_tasks_menu(message, state)
            return
        assignment_id = display_map.get(text)
        if assignment_id is None:
            await message.answer(
                t("task_delete_invalid", lang),
                reply_markup=task_delete_keyboard(list(display_map.keys()), lang, include_tabs=False),
            )
            return
        await state.set_state(SettingsFlow.task_delete_confirm)
        await state.update_data(task_delete_assignment_id=assignment_id)
        await message.answer(
            await _task_delete_summary(message.from_user.id, group_id, assignment_id, lang),
            reply_markup=task_delete_confirm_keyboard(lang, include_tabs=False),
        )
        return

    if current_state == SettingsFlow.task_delete_confirm.state:
        data = await state.get_data()
        group_id = int(data["selected_group"])
        assignment_id = str(data.get("task_delete_assignment_id") or "")
        display_map: dict[str, str] = data.get("task_delete_map", {})
        if _is_back_btn(message, lang):
            await state.set_state(SettingsFlow.task_delete_select)
            await message.answer(
                t("task_delete_prompt", lang),
                reply_markup=task_delete_keyboard(list(display_map.keys()), lang, include_tabs=False),
            )
            return
        if _is_confirm_btn(message, lang):
            async with SessionLocal() as session:
                await _task_service(session).delete_assignment(
                    actor_user_id=message.from_user.id,
                    group_id=group_id,
                    assignment_id=assignment_id,
                )
            await state.set_state(SettingsFlow.tasks_menu)
            await state.update_data(task_delete_assignment_id=None, task_delete_map={})
            await message.answer(
                t("task_deleted", lang),
                reply_markup=tasks_menu_keyboard(lang, include_tabs=False),
            )
            return
        await message.answer(
            await _task_delete_summary(message.from_user.id, group_id, assignment_id, lang),
            reply_markup=task_delete_confirm_keyboard(lang, include_tabs=False),
        )
        return

    if current_state == SettingsFlow.tasks_executor_menu.state:
        if _is_back_btn(message, lang):
            await state.clear()
            await message.answer(
                t("main_menu", lang),
                reply_markup=main_menu_keyboard(lang, dashboard_url=(get_settings().webapp_url or get_settings().dashboard_url)),
            )
            return
        if _is_task_executor_bot_btn(message, lang):
            group_map = await _bot_task_group_display_map()
            await state.update_data(
                task_executor_type="bot",
                task_agent_id=None,
                task_agent_map={},
                task_group_map=group_map,
            )
            await _open_task_group_selection(message, state, group_map, page=1)
            return
        if _is_task_executor_agent_btn(message, lang):
            display_map = await _all_active_agent_display_map(message.from_user.id)
            if not display_map:
                await message.answer(t("task_agent_none", lang), reply_markup=task_executor_keyboard(lang, include_tabs=False))
                return
            await state.set_state(SettingsFlow.task_reply_agent_input)
            await state.update_data(task_executor_type="agent", task_agent_map=display_map, task_agent_id=None, task_group_map={})
            await message.answer(
                t("task_agent_prompt", lang),
                reply_markup=task_agent_keyboard(list(display_map.keys()), lang, include_tabs=False),
            )
            return
        await message.answer(t("task_executor_invalid", lang), reply_markup=task_executor_keyboard(lang, include_tabs=False))
        return

    if current_state == SettingsFlow.task_target_group_input.state:
        data = await state.get_data()
        executor_type = str(data.get("task_executor_type") or "bot")
        group_map: dict[str, dict[str, int | str | None]] = data.get("task_group_map", {})
        current_page = int(data.get("task_group_page") or 1)
        if _is_back_btn(message, lang):
            if executor_type == "agent":
                agent_map: dict[str, int] = data.get("task_agent_map", {})
                await state.set_state(SettingsFlow.task_reply_agent_input)
                await message.answer(
                    t("task_agent_prompt", lang),
                    reply_markup=task_agent_keyboard(list(agent_map.keys()), lang, include_tabs=False),
                )
            else:
                await state.set_state(SettingsFlow.tasks_executor_menu)
                await message.answer(
                    t("task_executor_prompt", lang),
                    reply_markup=task_executor_keyboard(lang, include_tabs=False),
                )
            return
        if _is_prev_btn(message, lang):
            await _open_task_group_selection(message, state, group_map, page=current_page - 1)
            return
        if _is_next_btn(message, lang):
            await _open_task_group_selection(message, state, group_map, page=current_page + 1)
            return
        if _is_page_label(message, lang):
            await _open_task_group_selection(message, state, group_map, page=current_page)
            return
        group_ref = group_map.get(text)
        if group_ref is None:
            await message.answer(
                t("task_group_invalid", lang),
                reply_markup=task_group_keyboard(_task_group_page(group_map, current_page), lang, include_tabs=False),
            )
            return
        group_id = group_ref.get("group_id")
        if group_id is None:
            async with SessionLocal() as session:
                group = await upsert_group(
                    session,
                    tg_group_id=int(group_ref["tg_group_id"]),
                    title=str(group_ref["title"]),
                    is_active=True,
                )
                role = (
                    await session.execute(
                        select(GroupAdminRole).where(
                            GroupAdminRole.group_id == group.id,
                            GroupAdminRole.user_id == message.from_user.id,
                        )
                    )
                ).scalar_one_or_none()
                if role is None:
                    session.add(GroupAdminRole(group_id=group.id, user_id=message.from_user.id, role="admin"))
                await session.commit()
                group_id = int(group.id)
                group_ref["group_id"] = group_id
                group_map[text] = group_ref
        await state.update_data(selected_group=group_id, task_group_map=group_map)
        await _open_tasks_menu(message, state)
        return

    if current_state == SettingsFlow.task_reply_keyword_input.state:
        data = await state.get_data()
        group_id = int(data["selected_group"])
        executor_type = str(data.get("task_executor_type") or "bot")
        if _is_back_btn(message, lang):
            await _open_tasks_menu(message, state)
            return
        if not text:
            await message.answer(t("task_keyword_invalid", lang), reply_markup=tasks_menu_keyboard(lang, include_tabs=False))
            return
        if executor_type == "agent":
            await state.set_state(SettingsFlow.task_reply_visibility_input)
            await state.update_data(selected_group=group_id, task_keyword=text, task_reply_mode=None)
            await message.answer(
                t("task_reply_visibility_prompt", lang),
                reply_markup=task_reply_visibility_keyboard(lang, include_tabs=False),
            )
        else:
            await state.set_state(SettingsFlow.task_reply_template_input)
            await state.update_data(selected_group=group_id, task_keyword=text, task_reply_mode="public")
            await message.answer(t("task_template_prompt", lang), reply_markup=tasks_menu_keyboard(lang, include_tabs=False))
        return

    if current_state == SettingsFlow.task_reply_visibility_input.state:
        data = await state.get_data()
        if _is_back_btn(message, lang):
            await state.set_state(SettingsFlow.task_reply_keyword_input)
            await message.answer(t("task_keyword_prompt", lang), reply_markup=tasks_menu_keyboard(lang, include_tabs=False))
            return
        reply_mode: str | None = None
        if _is_task_reply_public_btn(message, lang):
            reply_mode = "public"
        elif _is_task_reply_private_btn(message, lang):
            reply_mode = "private"
        if reply_mode is None:
            await message.answer(
                t("task_reply_visibility_invalid", lang),
                reply_markup=task_reply_visibility_keyboard(lang, include_tabs=False),
            )
            return
        await state.set_state(SettingsFlow.task_reply_template_input)
        await state.update_data(task_reply_mode=reply_mode)
        await message.answer(t("task_template_prompt", lang), reply_markup=tasks_menu_keyboard(lang, include_tabs=False))
        return

    if current_state == SettingsFlow.task_reply_agent_input.state:
        data = await state.get_data()
        display_map: dict[str, int] = data.get("task_agent_map", {})
        if _is_back_btn(message, lang):
            await state.set_state(SettingsFlow.tasks_executor_menu)
            await message.answer(t("task_executor_prompt", lang), reply_markup=task_executor_keyboard(lang, include_tabs=False))
            return
        agent_id = display_map.get(text)
        if agent_id is None:
            await message.answer(t("task_agent_invalid", lang), reply_markup=task_agent_keyboard(list(display_map.keys()), lang, include_tabs=False))
            return
        group_map = await _agent_task_group_display_map(message.from_user.id, agent_id)
        if not group_map:
            await message.answer(t("task_agent_group_none", lang), reply_markup=task_agent_keyboard(list(display_map.keys()), lang, include_tabs=False))
            return
        await state.update_data(task_agent_id=agent_id, task_group_map=group_map)
        await _open_task_group_selection(message, state, group_map, page=1)
        return

    if current_state == SettingsFlow.task_reply_template_input.state:
        data = await state.get_data()
        group_id = int(data["selected_group"])
        keyword = str(data.get("task_keyword") or "").strip()
        executor_type = str(data.get("task_executor_type") or "bot")
        agent_id = int(data["task_agent_id"]) if data.get("task_agent_id") is not None else None
        reply_mode = str(data.get("task_reply_mode") or "public")
        if _is_back_btn(message, lang):
            if executor_type == "agent":
                await state.set_state(SettingsFlow.task_reply_visibility_input)
                await message.answer(
                    t("task_reply_visibility_prompt", lang),
                    reply_markup=task_reply_visibility_keyboard(lang, include_tabs=False),
                )
            else:
                await state.set_state(SettingsFlow.task_reply_keyword_input)
                await message.answer(t("task_keyword_prompt", lang), reply_markup=tasks_menu_keyboard(lang, include_tabs=False))
            return
        if not text:
            await message.answer(t("task_template_invalid", lang), reply_markup=tasks_menu_keyboard(lang, include_tabs=False))
            return
        async with SessionLocal() as session:
            await _task_service(session).save_assignment(
                actor_user_id=message.from_user.id,
                group_id=group_id,
                task_key="reply_message",
                executor_type=executor_type,
                agent_id=agent_id,
                conditions={"text_contains": keyword},
                config={"message_template": text, "reply_mode": reply_mode},
            )
        executor_label = t("task_executor_bot", lang) if executor_type == "bot" else t("task_executor_agent", lang)
        if executor_type == "agent" and agent_id is not None:
            agent_map: dict[str, int] = data.get("task_agent_map", {})
            for label, mapped_id in agent_map.items():
                if mapped_id == agent_id:
                    executor_label = label.replace("👤 ", "", 1)
                    break
        await state.set_state(SettingsFlow.tasks_menu)
        await state.update_data(
            selected_group=group_id,
            task_keyword=None,
            task_executor_type=None,
            task_agent_id=None,
            task_agent_map={},
            task_reply_mode=None,
        )
        await message.answer(
            f"{t('task_saved', lang)}\n\n{t('task_saved_details', lang, keyword=keyword, executor=executor_label)}",
            reply_markup=tasks_menu_keyboard(lang, include_tabs=False),
        )
        return

    if current_state == SettingsFlow.task_notify_keyword_input.state:
        data = await state.get_data()
        group_id = int(data["selected_group"])
        if _is_back_btn(message, lang):
            await _open_tasks_menu(message, state)
            return
        keywords = _parse_bulk_keywords(text)
        if not keywords:
            await message.answer(t("task_keyword_invalid", lang), reply_markup=tasks_menu_keyboard(lang, include_tabs=False))
            return
        await state.set_state(SettingsFlow.task_notify_destination_input)
        await state.update_data(selected_group=group_id, task_keywords=keywords)
        await message.answer(
            t("task_notify_destination_prompt", lang),
            reply_markup=tasks_menu_keyboard(lang, include_tabs=False),
        )
        return

    if current_state == SettingsFlow.task_notify_destination_input.state:
        data = await state.get_data()
        group_id = int(data["selected_group"])
        if _is_back_btn(message, lang):
            await state.set_state(SettingsFlow.task_notify_keyword_input)
            await message.answer(t("task_notify_keyword_prompt", lang), reply_markup=tasks_menu_keyboard(lang, include_tabs=False))
            return
        if not text:
            await message.answer(
                t("task_notify_destination_invalid", lang),
                reply_markup=tasks_menu_keyboard(lang, include_tabs=False),
            )
            return
        await state.set_state(SettingsFlow.task_notify_delivery_mode_input)
        await state.update_data(selected_group=group_id, task_notify_destination=text)
        await message.answer(
            t("task_notify_delivery_mode_prompt", lang),
            reply_markup=task_notify_delivery_mode_keyboard(lang, include_tabs=False),
        )
        return

    if current_state == SettingsFlow.task_notify_delivery_mode_input.state:
        data = await state.get_data()
        group_id = int(data["selected_group"])
        if _is_back_btn(message, lang):
            await state.set_state(SettingsFlow.task_notify_destination_input)
            await message.answer(
                t("task_notify_destination_prompt", lang),
                reply_markup=tasks_menu_keyboard(lang, include_tabs=False),
            )
            return
        delivery_mode = _notify_delivery_mode_map(lang).get(_text(message))
        if delivery_mode is None:
            await message.answer(
                t("task_notify_delivery_mode_invalid", lang),
                reply_markup=task_notify_delivery_mode_keyboard(lang, include_tabs=False),
            )
            return
        await state.update_data(selected_group=group_id, task_notify_delivery_mode=delivery_mode)
        if _notify_delivery_mode_requires_text(delivery_mode):
            await state.set_state(SettingsFlow.task_notify_template_input)
            await message.answer(t("task_template_prompt", lang), reply_markup=tasks_menu_keyboard(lang, include_tabs=False))
            return
        await state.set_state(SettingsFlow.task_notify_delete_after_input)
        await state.update_data(task_notify_template=None)
        await message.answer(t("task_delete_after_prompt", lang), reply_markup=tasks_menu_keyboard(lang, include_tabs=False))
        return

    if current_state == SettingsFlow.task_notify_template_input.state:
        data = await state.get_data()
        group_id = int(data["selected_group"])
        if _is_back_btn(message, lang):
            await state.set_state(SettingsFlow.task_notify_delivery_mode_input)
            await message.answer(
                t("task_notify_delivery_mode_prompt", lang),
                reply_markup=task_notify_delivery_mode_keyboard(lang, include_tabs=False),
            )
            return
        if not text:
            await message.answer(t("task_template_invalid", lang), reply_markup=tasks_menu_keyboard(lang, include_tabs=False))
            return
        await state.set_state(SettingsFlow.task_notify_delete_after_input)
        await state.update_data(selected_group=group_id, task_notify_template=text)
        await message.answer(t("task_delete_after_prompt", lang), reply_markup=tasks_menu_keyboard(lang, include_tabs=False))
        return

    if current_state == SettingsFlow.task_notify_delete_after_input.state:
        data = await state.get_data()
        group_id = int(data["selected_group"])
        if _is_back_btn(message, lang):
            delivery_mode = str(data.get("task_notify_delivery_mode") or "text")
            if _notify_delivery_mode_requires_text(delivery_mode):
                await state.set_state(SettingsFlow.task_notify_template_input)
                await message.answer(t("task_template_prompt", lang), reply_markup=tasks_menu_keyboard(lang, include_tabs=False))
                return
            await state.set_state(SettingsFlow.task_notify_delivery_mode_input)
            await message.answer(
                t("task_notify_delivery_mode_prompt", lang),
                reply_markup=task_notify_delivery_mode_keyboard(lang, include_tabs=False),
            )
            return
        delete_after_seconds = _parse_delete_after_seconds(text)
        if delete_after_seconds is None:
            await message.answer(t("task_delete_after_invalid", lang), reply_markup=tasks_menu_keyboard(lang, include_tabs=False))
            return
        keywords = [str(item).strip() for item in data.get("task_keywords") or [] if str(item).strip()]
        keyword_summary = ", ".join(keywords)
        destination = str(data.get("task_notify_destination") or "").strip()
        template = str(data.get("task_notify_template") or "").strip()
        delivery_mode = str(data.get("task_notify_delivery_mode") or "text").strip() or "text"
        async with SessionLocal() as session:
            await _task_service(session).save_assignment(
                actor_user_id=message.from_user.id,
                group_id=group_id,
                task_key="notify_destination",
                executor_type="bot",
                conditions={"text_contains_any": keywords},
                config={
                    "destination": destination,
                    "delivery_mode": delivery_mode,
                    "delete_after_seconds": delete_after_seconds,
                    **({"message_template": template} if template else {}),
                },
            )
        await state.set_state(SettingsFlow.tasks_menu)
        await state.update_data(
            selected_group=group_id,
            task_keywords=None,
            task_notify_destination=None,
            task_notify_delivery_mode=None,
            task_notify_template=None,
        )
        await message.answer(
            f"{t('task_notify_saved', lang)}\n\n{t('task_notify_saved_details', lang, keyword=keyword_summary, destination=destination)}",
            reply_markup=tasks_menu_keyboard(lang, include_tabs=False),
        )
        return

    if current_state == SettingsFlow.announcement_schedule_text.state:
        data = await state.get_data()
        group_id = data["selected_group"]
        if _is_back_btn(message, lang):
            await _open_announcements_menu(message, state, group_id)
            return
        await state.set_state(SettingsFlow.announcement_schedule_time)
        await state.update_data(selected_group=group_id, announcement_schedule_text=text)
        await message.answer(
            t("announcement_time_prompt", lang),
            reply_markup=announcements_menu_keyboard(lang, include_tabs=False),
        )
        return

    if current_state == SettingsFlow.announcement_schedule_time.state:
        data = await state.get_data()
        group_id = data["selected_group"]
        if _is_back_btn(message, lang):
            await _open_announcements_menu(message, state, group_id)
            return
        schedule = _parse_schedule_time(text)
        if schedule is None:
            await message.answer(
                t("announcement_schedule_invalid_time", lang),
                reply_markup=announcements_menu_keyboard(lang, include_tabs=False),
            )
            return
        send_at, cron_expression = schedule
        await state.set_state(SettingsFlow.announcement_schedule_delete_after)
        await state.update_data(
            selected_group=group_id,
            announcement_schedule_send_at=send_at.isoformat(timespec="minutes"),
            announcement_schedule_cron=cron_expression,
            announcement_schedule_input=text,
        )
        await message.answer(
            t("announcement_delete_after_prompt", lang),
            reply_markup=announcements_menu_keyboard(lang, include_tabs=False),
        )
        return

    if current_state == SettingsFlow.announcement_schedule_delete_after.state:
        data = await state.get_data()
        group_id = data["selected_group"]
        if _is_back_btn(message, lang):
            await state.set_state(SettingsFlow.announcement_schedule_time)
            await message.answer(
                t("announcement_time_prompt", lang),
                reply_markup=announcements_menu_keyboard(lang, include_tabs=False),
            )
            return
        delete_after_seconds = _parse_delete_after_seconds(text)
        if delete_after_seconds is None:
            await message.answer(
                t("announcement_delete_after_invalid", lang),
                reply_markup=announcements_menu_keyboard(lang, include_tabs=False),
            )
            return
        send_at = datetime.fromisoformat(str(data["announcement_schedule_send_at"]))
        cron_expression = data.get("announcement_schedule_cron")
        async with SessionLocal() as session:
            entry = await ScheduledMessageService(session).save_entry(
                group_id=group_id,
                text=str(data["announcement_schedule_text"]),
                schedule=str(data.get("announcement_schedule_input") or cron_expression or data["announcement_schedule_send_at"]),
                delete_after_seconds=delete_after_seconds,
            )
        if send_at <= datetime.utcnow():
            await _send_due_announcements(message, group_id)
        else:
            _schedule_announcement_task(message.bot, group_id, str(entry["id"]))
        await _open_announcements_menu(message, state, group_id)
        await message.answer(
            t("announcement_schedule_saved", lang, send_at=entry["send_at"]),
            reply_markup=announcements_menu_keyboard(lang, include_tabs=False),
        )
        return

    if current_state == SettingsFlow.announcement_edit_select.state:
        data = await state.get_data()
        group_id = int(data["selected_group"])
        display_map: dict[str, str] = data.get("announcement_edit_map", {})
        if _is_back_btn(message, lang):
            await _open_announcements_menu(message, state, group_id)
            return
        entry_id = display_map.get(text)
        if entry_id is None:
            await message.answer(
                t("announcement_edit_invalid", lang),
                reply_markup=task_delete_keyboard(list(display_map.keys()), lang, include_tabs=False),
            )
            return
        entries = await _announcement_entries(group_id)
        entry = next((item for item in entries if str(item.get("id")) == entry_id), None)
        if entry is None:
            await _open_announcements_menu(message, state, group_id)
            return
        await state.set_state(SettingsFlow.announcement_edit_text)
        await state.update_data(
            announcement_edit_entry_id=entry_id,
            announcement_edit_existing=entry,
        )
        await message.answer(
            f"{await _announcement_summary(group_id, entry_id, lang)}\n\n{t('announcement_schedule_prompt', lang)}",
            reply_markup=announcements_menu_keyboard(lang, include_tabs=False),
        )
        return

    if current_state == SettingsFlow.announcement_edit_text.state:
        data = await state.get_data()
        group_id = int(data["selected_group"])
        if _is_back_btn(message, lang):
            await state.set_state(SettingsFlow.announcement_edit_select)
            display_map: dict[str, str] = data.get("announcement_edit_map", {})
            await message.answer(
                t("announcement_edit_prompt", lang),
                reply_markup=task_delete_keyboard(list(display_map.keys()), lang, include_tabs=False),
            )
            return
        if not text:
            await message.answer(
                t("announcement_schedule_prompt", lang),
                reply_markup=announcements_menu_keyboard(lang, include_tabs=False),
            )
            return
        await state.set_state(SettingsFlow.announcement_edit_time)
        await state.update_data(announcement_schedule_text=text)
        await message.answer(
            t("announcement_time_prompt", lang),
            reply_markup=announcements_menu_keyboard(lang, include_tabs=False),
        )
        return

    if current_state == SettingsFlow.announcement_edit_time.state:
        data = await state.get_data()
        group_id = int(data["selected_group"])
        if _is_back_btn(message, lang):
            await state.set_state(SettingsFlow.announcement_edit_text)
            await message.answer(
                t("announcement_schedule_prompt", lang),
                reply_markup=announcements_menu_keyboard(lang, include_tabs=False),
            )
            return
        schedule = _parse_schedule_time(text)
        if schedule is None:
            await message.answer(
                t("announcement_schedule_invalid_time", lang),
                reply_markup=announcements_menu_keyboard(lang, include_tabs=False),
            )
            return
        send_at, cron_expression = schedule
        await state.set_state(SettingsFlow.announcement_edit_delete_after)
        await state.update_data(
            selected_group=group_id,
            announcement_schedule_send_at=send_at.isoformat(timespec="minutes"),
            announcement_schedule_cron=cron_expression,
            announcement_schedule_input=text,
        )
        await message.answer(
            t("announcement_delete_after_prompt", lang),
            reply_markup=announcements_menu_keyboard(lang, include_tabs=False),
        )
        return

    if current_state == SettingsFlow.announcement_edit_delete_after.state:
        data = await state.get_data()
        group_id = int(data["selected_group"])
        if _is_back_btn(message, lang):
            await state.set_state(SettingsFlow.announcement_edit_time)
            await message.answer(
                t("announcement_time_prompt", lang),
                reply_markup=announcements_menu_keyboard(lang, include_tabs=False),
            )
            return
        delete_after_seconds = _parse_delete_after_seconds(text)
        if delete_after_seconds is None:
            await message.answer(
                t("announcement_delete_after_invalid", lang),
                reply_markup=announcements_menu_keyboard(lang, include_tabs=False),
            )
            return
        send_at = datetime.fromisoformat(str(data["announcement_schedule_send_at"]))
        entry_id = str(data.get("announcement_edit_entry_id") or "")
        async with SessionLocal() as session:
            entry = await ScheduledMessageService(session).save_entry(
                group_id=group_id,
                text=str(data["announcement_schedule_text"]),
                schedule=str(data.get("announcement_schedule_input") or data["announcement_schedule_send_at"]),
                entry_id=entry_id,
                delete_after_seconds=delete_after_seconds,
            )
        if send_at <= datetime.utcnow():
            await _send_due_announcements(message, group_id)
        else:
            _schedule_announcement_task(message.bot, group_id, str(entry["id"]))
        await state.set_state(SettingsFlow.announcements_menu)
        await state.update_data(
            announcement_edit_entry_id=None,
            announcement_edit_existing=None,
            announcement_edit_map={},
        )
        await message.answer(
            t("announcement_edit_saved", lang, send_at=entry["send_at"]),
            reply_markup=announcements_menu_keyboard(lang, include_tabs=False),
        )
        return

    if current_state == SettingsFlow.announcement_delete_select.state:
        data = await state.get_data()
        group_id = int(data["selected_group"])
        display_map: dict[str, str] = data.get("announcement_delete_map", {})
        if _is_back_btn(message, lang):
            await _open_announcements_menu(message, state, group_id)
            return
        entry_id = display_map.get(text)
        if entry_id is None:
            await message.answer(
                t("announcement_delete_invalid", lang),
                reply_markup=task_delete_keyboard(list(display_map.keys()), lang, include_tabs=False),
            )
            return
        await state.set_state(SettingsFlow.announcement_delete_confirm)
        await state.update_data(announcement_delete_entry_id=entry_id)
        await message.answer(
            await _announcement_summary(group_id, entry_id, lang, delete_mode=True),
            reply_markup=task_delete_confirm_keyboard(lang, include_tabs=False),
        )
        return

    if current_state == SettingsFlow.announcement_delete_confirm.state:
        data = await state.get_data()
        group_id = int(data["selected_group"])
        entry_id = str(data.get("announcement_delete_entry_id") or "")
        display_map: dict[str, str] = data.get("announcement_delete_map", {})
        if _is_back_btn(message, lang):
            await state.set_state(SettingsFlow.announcement_delete_select)
            await message.answer(
                t("announcement_delete_prompt", lang),
                reply_markup=task_delete_keyboard(list(display_map.keys()), lang, include_tabs=False),
            )
            return
        if _is_confirm_btn(message, lang):
            async with SessionLocal() as session:
                await ScheduledMessageService(session).delete_entry(group_id=group_id, entry_id=entry_id)
            await state.set_state(SettingsFlow.announcements_menu)
            await state.update_data(announcement_delete_entry_id=None, announcement_delete_map={})
            await message.answer(
                t("announcement_deleted", lang),
                reply_markup=announcements_menu_keyboard(lang, include_tabs=False),
            )
            return
        await message.answer(
            await _announcement_summary(group_id, entry_id, lang, delete_mode=True),
            reply_markup=task_delete_confirm_keyboard(lang, include_tabs=False),
        )
        return

    if current_state == SettingsFlow.announcement_bulk_groups.state:
        data = await state.get_data()
        group_id = data["selected_group"]
        candidates: list[dict] = data.get("announcement_bulk_candidates", [])
        display_map: dict[str, int] = data.get("announcement_bulk_display_map", {})
        selected_group_ids = set(int(x) for x in data.get("announcement_bulk_groups", []))

        if _is_back_btn(message, lang):
            await _open_announcements_menu(message, state, group_id)
            return
        if _is_clear_selected_groups_btn(message, lang):
            selected_group_ids = set()
        elif _is_send_bulk_message_btn(message, lang):
            if not selected_group_ids:
                await message.answer(
                    t("announcement_bulk_none_selected", lang),
                    reply_markup=bulk_groups_keyboard(candidates, selected_group_ids, lang, include_tabs=False),
                )
                return
            await state.set_state(SettingsFlow.announcement_bulk_text)
            await state.update_data(selected_group=group_id, announcement_bulk_groups=list(selected_group_ids))
            await message.answer(
                t("announcement_bulk_prompt", lang),
                reply_markup=announcements_menu_keyboard(lang, include_tabs=False),
            )
            return
        else:
            selected_group_id = display_map.get(text)
            if selected_group_id is None:
                await message.answer(
                    t("unknown_action", lang),
                    reply_markup=bulk_groups_keyboard(candidates, selected_group_ids, lang, include_tabs=False),
                )
                return
            if selected_group_id in selected_group_ids:
                selected_group_ids.remove(selected_group_id)
            else:
                selected_group_ids.add(selected_group_id)

        new_display_map = _build_bulk_display_map(candidates, selected_group_ids)
        await state.update_data(
            announcement_bulk_groups=list(selected_group_ids),
            announcement_bulk_display_map=new_display_map,
        )
        selected_titles = ", ".join(str(group["title"]) for group in candidates if int(group["id"]) in selected_group_ids) or "-"
        await message.answer(
            f"{t('announcement_bulk_help', lang)}\n\n{t('announcement_bulk_groups_selected', lang, groups=selected_titles)}",
            reply_markup=bulk_groups_keyboard(candidates, selected_group_ids, lang, include_tabs=False),
        )
        return

    if current_state == SettingsFlow.announcement_bulk_text.state:
        data = await state.get_data()
        group_ids = [int(x) for x in data.get("announcement_bulk_groups", [])]
        if _is_back_btn(message, lang):
            await _open_announcements_menu(message, state, data["selected_group"])
            return
        if not group_ids:
            await message.answer(
                t("announcement_bulk_none_selected", lang),
                reply_markup=announcements_menu_keyboard(lang, include_tabs=False),
            )
            return
        sent = 0
        async with SessionLocal() as session:
            groups = (
                await session.execute(select(Group).where(Group.id.in_(group_ids)))
            ).scalars().all()
        for group in groups:
            try:
                await message.bot.send_message(group.tg_group_id, text)
                sent += 1
            except Exception:
                continue
        await _open_announcements_menu(message, state, data["selected_group"])
        await message.answer(
            t("announcement_bulk_sent", lang, count=sent),
            reply_markup=announcements_menu_keyboard(lang, include_tabs=False),
        )
        return

    if current_state == SettingsFlow.agents_menu.state:
        data = await state.get_data()
        group_id = data["selected_group"]

        if _is_back_btn(message, lang):
            await _open_agents_list_menu(message, state, group_id)
            return
        if _is_link_account_btn(message, lang):
            await state.set_state(SettingsFlow.agents_phone_input)
            await state.update_data(selected_group=group_id)
            await message.answer(t("agent_link_prompt", lang), reply_markup=agents_menu_keyboard(lang, include_tabs=False))
            return
        if _is_my_agents_btn(message, lang):
            await _open_agents_list_menu(message, state, group_id)
            return
        if _is_agent_jobs_btn(message, lang):
            await _open_agent_jobs_menu(message, state, group_id)
            return
        await message.answer(
            await _agents_panel_text(message.from_user.id, group_id, lang),
            reply_markup=agents_menu_keyboard(lang, include_tabs=False),
        )
        return

    if current_state == SettingsFlow.agents_phone_input.state:
        data = await state.get_data()
        group_id = data["selected_group"]
        if _is_back_btn(message, lang):
            await _open_agents_menu(message, state, group_id)
            return
        try:
            async with SessionLocal() as session:
                agent = await AgentService(session).start_agent_login(
                    actor_user_id=message.from_user.id,
                    group_id=group_id,
                    phone_number=text,
                    auth_service=get_agent_auth_service(),
                )
        except Exception:
            await message.answer(t("agent_link_error", lang), reply_markup=agents_menu_keyboard(lang, include_tabs=False))
            return
        await state.set_state(SettingsFlow.agents_code_input)
        await state.update_data(selected_group=group_id, agent_auth_id=agent.id)
        await message.answer(t("agent_code_prompt", lang), reply_markup=agents_menu_keyboard(lang, include_tabs=False))
        return

    if current_state == SettingsFlow.agents_code_input.state:
        data = await state.get_data()
        group_id = data["selected_group"]
        agent_id = int(data["agent_auth_id"])
        if _is_back_btn(message, lang):
            await _open_agents_menu(message, state, group_id)
            return
        try:
            async with SessionLocal() as session:
                agent = await AgentService(session).complete_agent_code(
                    actor_user_id=message.from_user.id,
                    agent_id=agent_id,
                    code=text,
                    auth_service=get_agent_auth_service(),
                )
        except AgentAuthStateError:
            await _open_agents_menu(message, state, group_id)
            await message.answer(t("agent_auth_expired", lang), reply_markup=agents_menu_keyboard(lang, include_tabs=False))
            return
        except AgentTelegramAuthError:
            await message.answer(t("agent_code_invalid", lang), reply_markup=agents_menu_keyboard(lang, include_tabs=False))
            return
        if agent.auth_state == "pending_2fa":
            await state.set_state(SettingsFlow.agents_2fa_input)
            await state.update_data(selected_group=group_id, agent_auth_id=agent.id)
            await message.answer(t("agent_2fa_required", lang), reply_markup=agents_menu_keyboard(lang, include_tabs=False))
            await message.answer(t("agent_2fa_prompt", lang), reply_markup=agents_menu_keyboard(lang, include_tabs=False))
            return
        await _open_agents_menu(message, state, group_id)
        await message.answer(t("agent_link_success", lang), reply_markup=agents_menu_keyboard(lang, include_tabs=False))
        return

    if current_state == SettingsFlow.agents_2fa_input.state:
        data = await state.get_data()
        group_id = data["selected_group"]
        agent_id = int(data["agent_auth_id"])
        if _is_back_btn(message, lang):
            await _open_agents_menu(message, state, group_id)
            return
        try:
            async with SessionLocal() as session:
                await AgentService(session).complete_agent_password(
                    actor_user_id=message.from_user.id,
                    agent_id=agent_id,
                    password=text,
                    auth_service=get_agent_auth_service(),
                )
        except AgentAuthStateError:
            await _open_agents_menu(message, state, group_id)
            await message.answer(t("agent_auth_expired", lang), reply_markup=agents_menu_keyboard(lang, include_tabs=False))
            return
        except AgentTelegramAuthError:
            await message.answer(t("agent_2fa_invalid", lang), reply_markup=agents_menu_keyboard(lang, include_tabs=False))
            return
        await _open_agents_menu(message, state, group_id)
        await message.answer(t("agent_link_success", lang), reply_markup=agents_menu_keyboard(lang, include_tabs=False))
        return

    if current_state == SettingsFlow.agents_list_menu.state:
        data = await state.get_data()
        group_id = data["selected_group"]
        display_map: dict[str, int] = data.get("agent_display_map", {})
        if _is_back_btn(message, lang):
            await state.clear()
            await message.answer(
                t("main_menu", lang),
                reply_markup=main_menu_keyboard(lang, dashboard_url=(get_settings().webapp_url or get_settings().dashboard_url)),
            )
            return
        if _is_link_account_btn(message, lang):
            await state.set_state(SettingsFlow.agents_phone_input)
            await state.update_data(selected_group=group_id)
            await message.answer(t("agent_link_prompt", lang), reply_markup=agent_list_keyboard(list(display_map.keys()), lang, include_tabs=False))
            return
        agent_id = display_map.get(text)
        if agent_id is None:
            await message.answer(
                t("unknown_action", lang),
                reply_markup=agent_list_keyboard(list(display_map.keys()), lang, include_tabs=False),
            )
            return
        await _open_selected_agent_menu(message, state, agent_id, group_id)
        return

    if current_state == SettingsFlow.agents_selected_menu.state:
        data = await state.get_data()
        group_id = data["selected_group"]
        agent_id = int(data["selected_agent_id"])
        if _is_back_btn(message, lang):
            await _open_agents_list_menu(message, state, group_id)
            return
        if _is_agent_jobs_btn(message, lang):
            await state.update_data(selected_group=group_id, selected_agent_id=agent_id)
            await _open_agent_jobs_menu(message, state, group_id)
            return
        if _is_create_job_btn(message, lang):
            await state.set_state(SettingsFlow.agents_job_create)
            await state.update_data(selected_group=group_id, selected_agent_id=agent_id)
            await message.answer(t("agent_jobs_prompt", lang), reply_markup=agent_actions_keyboard(lang, include_tabs=False))
            return
        if _is_unlink_account_btn(message, lang):
            await _open_unlink_confirm_menu(message, state, agent_id, group_id)
            return
        await _open_selected_agent_menu(message, state, agent_id, group_id)
        return

    if current_state == SettingsFlow.agents_unlink_confirm.state:
        data = await state.get_data()
        group_id = data["selected_group"]
        agent_id = int(data["selected_agent_id"])
        if _is_back_btn(message, lang):
            await _open_selected_agent_menu(message, state, agent_id, group_id)
            return
        if _is_confirm_btn(message, lang):
            async with SessionLocal() as session:
                deleted = await AgentService(session).unlink_agent(actor_user_id=message.from_user.id, agent_id=agent_id)
            await _open_agents_list_menu(message, state, group_id)
            if deleted:
                display_map: dict[str, int] = (await state.get_data()).get("agent_display_map", {})
                await message.answer(
                    t("agent_unlink_success", lang),
                    reply_markup=agent_list_keyboard(list(display_map.keys()), lang, include_tabs=False),
                )
            return
        await _open_unlink_confirm_menu(message, state, agent_id, group_id)
        return

    if current_state == SettingsFlow.agents_jobs_menu.state:
        data = await state.get_data()
        group_id = data["selected_group"]
        if _is_back_btn(message, lang):
            if data.get("selected_agent_id"):
                await _open_selected_agent_menu(message, state, int(data["selected_agent_id"]), group_id)
            else:
                await _open_agents_menu(message, state, group_id)
            return
        if _is_create_job_btn(message, lang):
            await state.set_state(SettingsFlow.agents_job_create)
            await state.update_data(selected_group=group_id)
            await message.answer(t("agent_jobs_prompt", lang), reply_markup=agent_jobs_menu_keyboard(lang, include_tabs=False))
            return
        await message.answer(
            await _agent_jobs_text(message.from_user.id, group_id, lang),
            reply_markup=agent_jobs_menu_keyboard(lang, include_tabs=False),
        )
        return

    if current_state == SettingsFlow.agents_job_create.state:
        data = await state.get_data()
        group_id = data["selected_group"]
        if _is_back_btn(message, lang):
            if data.get("selected_agent_id"):
                await _open_selected_agent_menu(message, state, int(data["selected_agent_id"]), group_id)
            else:
                await _open_agent_jobs_menu(message, state, group_id)
            return
        parsed_job = _parse_agent_job_input(text)
        selected_agent_id = data.get("selected_agent_id")
        if selected_agent_id:
            job_type: str
            payload: dict[str, object]
            compact_parts = [part.strip() for part in text.split("|", maxsplit=1)]
            if not compact_parts or not compact_parts[0]:
                await message.answer(t("agent_jobs_invalid", lang), reply_markup=agent_actions_keyboard(lang, include_tabs=False))
                return
            job_type = compact_parts[0]
            payload = {}
            if len(compact_parts) == 2 and compact_parts[1]:
                try:
                    raw = json.loads(compact_parts[1])
                except Exception:
                    await message.answer(t("agent_jobs_invalid", lang), reply_markup=agent_actions_keyboard(lang, include_tabs=False))
                    return
                if not isinstance(raw, dict):
                    await message.answer(t("agent_jobs_invalid", lang), reply_markup=agent_actions_keyboard(lang, include_tabs=False))
                    return
                payload = raw
            async with SessionLocal() as session:
                service = AgentService(session)
                await service.create_job(
                    actor_user_id=message.from_user.id,
                    agent_id=int(selected_agent_id),
                    job_type=job_type,
                    job_payload=payload,
                )
            await _open_selected_agent_menu(message, state, int(selected_agent_id), group_id)
            await message.answer(t("job_created", lang), reply_markup=agent_actions_keyboard(lang, include_tabs=False))
            return
        if parsed_job is None:
            await message.answer(t("agent_jobs_invalid", lang), reply_markup=agent_jobs_menu_keyboard(lang, include_tabs=False))
            return
        account_id, job_type, payload = parsed_job
        async with SessionLocal() as session:
            service = AgentService(session)
            agent = await service.get_agent_by_external_account(
                actor_user_id=message.from_user.id,
                group_id=group_id,
                external_account_id=account_id,
            )
            if agent is None:
                await message.answer(t("agent_jobs_invalid", lang), reply_markup=agent_jobs_menu_keyboard(lang, include_tabs=False))
                return
            await service.create_job(
                actor_user_id=message.from_user.id,
                agent_id=agent.id,
                job_type=job_type,
                job_payload=payload,
            )
        await _open_agent_jobs_menu(message, state, group_id)
        await message.answer(t("job_created", lang), reply_markup=agent_jobs_menu_keyboard(lang, include_tabs=False))
        return

    if current_state == SettingsFlow.help_menu.state:
        if _is_back_btn(message, lang):
            await state.clear()
            await message.answer(
                t("main_menu", lang),
                reply_markup=main_menu_keyboard(lang, dashboard_url=(get_settings().webapp_url or get_settings().dashboard_url)),
            )
            return
        section = "overview"
        if _is_help_commands_btn(message, lang):
            section = "commands"
        elif _is_help_panels_btn(message, lang):
            section = "panels"
        elif _is_help_announcements_btn(message, lang):
            section = "announcements"
        await message.answer(await _help_panel_text(lang, section), reply_markup=help_menu_keyboard(lang, include_tabs=False))
        return

    if current_state == SettingsFlow.access_gate_menu.state:
        data = await state.get_data()
        group_id = data["selected_group"]
        candidates: list[dict] = data.get("access_gate_candidates", [])
        display_map: dict[str, int] = data.get("access_gate_display_map", {})
        selected = set(int(x) for x in data.get("access_gate_selected", []))

        if _is_back_btn(message, lang):
            await _open_moderation_menu(message, state, group_id)
            return

        if _is_clear_required_groups_btn(message, lang):
            async with SessionLocal() as session:
                await AccessGateService(session).clear_required_groups(group_id)
            cleared_display_map = _build_access_gate_display_map(candidates, set())
            await state.update_data(access_gate_selected=[], access_gate_display_map=cleared_display_map)
            await message.answer(
                f"{t('required_groups_cleared', lang)}\n\n{_access_gate_menu_text(lang, candidates, set())}",
                reply_markup=access_gate_keyboard(candidates, set(), lang, include_tabs=False),
            )
            return

        required_tg_group_id = display_map.get(text)
        if required_tg_group_id is None:
            await message.answer(
                t("unknown_action", lang),
                reply_markup=access_gate_keyboard(candidates, selected, lang, include_tabs=False),
            )
            return

        async with SessionLocal() as session:
            gate = AccessGateService(session)
            if required_tg_group_id in selected:
                await gate.remove_required_group(group_id, required_tg_group_id)
                selected.remove(required_tg_group_id)
            else:
                await gate.add_required_group(group_id, required_tg_group_id)
                selected.add(required_tg_group_id)

        new_display_map = _build_access_gate_display_map(candidates, selected)
        await state.update_data(access_gate_display_map=new_display_map, access_gate_selected=list(selected))
        await message.answer(
            _access_gate_menu_text(lang, candidates, selected),
            reply_markup=access_gate_keyboard(candidates, selected, lang, include_tabs=False),
        )
        return

    if current_state == SettingsFlow.plugins_menu.state:
        data = await state.get_data()
        group_id = data["selected_group"]
        display_map: dict[str, str] = data.get("plugin_display_map", {})

        if _is_back_btn(message, lang):
            await _open_group_selector(message, state, SettingsFlow.plugins_group, 1, "select_group_for_plugins")
            return

        if _is_refresh_btn(message, lang):
            await _open_plugins_menu(message, state, plugin_manager, group_id)
            return

        plugin_name = display_map.get(text)
        if not plugin_name:
            await message.answer(t("unknown_action", lang), reply_markup=plugins_menu_keyboard({}, lang, include_tabs=False))
            return

        async with SessionLocal() as session:
            service = PluginService(session)
            enabled = await service.is_enabled(group_id, plugin_name)
            await service.set_enabled(group_id, plugin_name, not enabled)

        await _open_plugins_menu(message, state, plugin_manager, group_id)
        return

    if current_state == SettingsFlow.analytics_menu.state:
        data = await state.get_data()
        group_id = data["selected_group"]

        if _is_back_btn(message, lang):
            await _open_group_selector(message, state, SettingsFlow.analytics_group, 1, "select_group_for_analytics")
            return
        if _is_refresh_analytics_btn(message, lang):
            await _open_analytics_menu(message, state, group_id)
            return

        await message.answer(t("unknown_action", lang), reply_markup=analytics_menu_keyboard(lang, include_tabs=False))
        return

    if current_state == SettingsFlow.language_menu.state:
        if _is_back_btn(message, lang):
            await state.clear()
            await message.answer(
                t("main_menu", lang),
                reply_markup=main_menu_keyboard(lang, dashboard_url=(get_settings().webapp_url or get_settings().dashboard_url)),
            )
            return

        if _is_lang_en_btn(message, lang) or _text(message).endswith("English"):
            new_lang = "en"
        elif _is_lang_ar_btn(message, lang) or _text(message).endswith("العربية"):
            new_lang = "ar"
        else:
            await message.answer(t("unknown_action", lang), reply_markup=language_keyboard(lang))
            return

        async with SessionLocal() as session:
            await UserService(session).set_language(
                tg_user_id=message.from_user.id,
                language_code=new_lang,
                username=message.from_user.username if message.from_user else None,
                full_name=message.from_user.full_name if message.from_user else None,
            )

        await state.clear()
        await message.answer(
            t("language_updated", new_lang),
            reply_markup=main_menu_keyboard(new_lang, dashboard_url=(get_settings().webapp_url or get_settings().dashboard_url)),
        )
        return

    logger.warning(
        "private_menu_unhandled_state",
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else None,
        state=current_state,
        text=text,
        data=await state.get_data(),
    )
    await message.answer(t("unknown_action", lang))
