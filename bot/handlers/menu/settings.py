from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ChatPermissions
from sqlalchemy import select

from bot.core.menu_engine import MenuEngine
from bot.core.plugin_manager import PluginManager
from bot.agents.service import AgentService
from bot.db.models import Group, ModerationLog
from bot.db.session import SessionLocal
from bot.handlers.menu.states import SettingsFlow
from bot.services.group_service import GroupService
from bot.services.moderation_enforcement_service import add_warning, maybe_mute_user_on_warning_limit, maybe_remove_user_on_warning_limit
from bot.services.permission_service import PermissionService
from bot.services.settings_service import SettingsService
from bot.utils.i18n import t

router = Router(name="settings_menu")
MOD_USER_ACTIONS = {"ban", "mute", "warn"}
MOD_PERMISSION_MAP = {
    "ban": "group.moderation.ban",
    "mute": "group.moderation.ban",
    "warn": "group.moderation.warn",
    "clean": "group.settings.update",
    "anti_links": "group.settings.update",
    "anti_spam": "group.settings.update",
    "anti_ads": "group.settings.update",
}


def _lang(call: CallbackQuery) -> str:
    if call.from_user and call.from_user.language_code:
        return "ar" if call.from_user.language_code.startswith("ar") else "en"
    return "en"


async def _group_add_url(call: CallbackQuery) -> str | None:
    try:
        me = await call.bot.get_me()
        return f"https://t.me/{me.username}?startgroup=true"
    except Exception:
        return None


async def _resolve_moderation_group(
    call: CallbackQuery,
    state: FSMContext,
) -> tuple[int, int] | None:
    data = await state.get_data()
    selected_group_id = data.get("selected_group")
    async with SessionLocal() as session:
        if selected_group_id is None:
            groups = await GroupService(session).list_admin_groups(call.from_user.id, page=1, page_size=1)
            if not groups.items:
                return None
            selected_group_id = groups.items[0]["id"]
            await state.update_data(selected_group=selected_group_id)
        group = (
            await session.execute(select(Group).where(Group.id == int(selected_group_id)))
        ).scalar_one_or_none()
        if not group:
            return None
        return group.id, group.tg_group_id


@router.callback_query(F.data == "menu:settings")
async def menu_settings(call: CallbackQuery, state: FSMContext, menu_engine: MenuEngine) -> None:
    async with SessionLocal() as session:
        groups_page = await GroupService(session).list_admin_groups(call.from_user.id, page=1, page_size=10)
    lang = _lang(call)
    await state.set_state(SettingsFlow.selecting_group)
    await state.update_data(group_page=1)
    if groups_page.total == 0:
        add_group_url = await _group_add_url(call)
        await call.message.edit_text(
            t("no_groups_found", lang),
            reply_markup=menu_engine.empty_group_selector(lang, add_group_url=add_group_url),
        )
        await call.answer()
        return
    await call.message.edit_text(
        t("select_group", lang),
        reply_markup=menu_engine.group_selector(groups_page, lang),
    )
    await call.answer()


@router.callback_query(F.data == "menu:main")
async def menu_main(call: CallbackQuery, state: FSMContext, menu_engine: MenuEngine) -> None:
    await state.clear()
    lang = _lang(call)
    await call.message.edit_text(t("main_menu", lang), reply_markup=menu_engine.main_menu(lang))
    await call.answer()


async def _section_panel(call: CallbackQuery, menu_engine: MenuEngine, title_key: str) -> None:
    lang = _lang(call)
    await call.message.edit_text(
        f"{t(title_key, lang)}\n\n{t('section_coming_soon', lang)}",
        reply_markup=menu_engine.section_menu(lang),
    )
    await call.answer()


async def _agents_list_text(user_id: int, group_id: int, lang: str) -> str:
    async with SessionLocal() as session:
        agents = await AgentService(session).list_agents(actor_user_id=user_id, group_id=group_id)
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


async def _agent_jobs_text(user_id: int, group_id: int, lang: str) -> str:
    async with SessionLocal() as session:
        service = AgentService(session)
        jobs = await service.list_jobs(actor_user_id=user_id, group_id=group_id, limit=5)
        agents = {agent.id: agent.external_account_id for agent in await service.list_agents(actor_user_id=user_id, group_id=group_id)}
    if not jobs:
        return t("agent_jobs_empty", lang)
    lines = [t("agent_jobs_overview", lang)]
    for job in jobs:
        lines.append(f"- {agents.get(job.agent_id, job.agent_id)} | {job.job_type} | {job.status}")
    return "\n".join(lines)


async def _open_agents_panel(call: CallbackQuery, state: FSMContext, menu_engine: MenuEngine, group_id: int) -> None:
    lang = _lang(call)
    await state.set_state(SettingsFlow.agents_menu)
    await state.update_data(selected_group=group_id)
    await call.message.edit_text(
        f"{t('agents', lang)}\n\n{t('agents_panel_help', lang)}",
        reply_markup=menu_engine.agents_menu(lang),
    )
    await call.answer()


async def _resolve_agents_group_id(call: CallbackQuery, state: FSMContext) -> int | None:
    data = await state.get_data()
    selected_group_id = data.get("selected_group")
    async with SessionLocal() as session:
        if selected_group_id is not None:
            can_manage = await PermissionService(session).can(int(selected_group_id), call.from_user.id, "group.settings.update")
            if can_manage:
                return int(selected_group_id)
        groups = await GroupService(session).list_admin_groups(call.from_user.id, page=1, page_size=1)
    if not groups.items:
        return None
    group_id = int(groups.items[0]["id"])
    await state.update_data(selected_group=group_id)
    return group_id


@router.callback_query(F.data == "menu:stats")
async def menu_stats(call: CallbackQuery, menu_engine: MenuEngine) -> None:
    await _section_panel(call, menu_engine, "stats")


@router.callback_query(F.data == "menu:members")
async def menu_members(call: CallbackQuery, menu_engine: MenuEngine) -> None:
    await _section_panel(call, menu_engine, "members")


@router.callback_query(F.data == "menu:announcements")
async def menu_announcements(call: CallbackQuery, menu_engine: MenuEngine) -> None:
    await _section_panel(call, menu_engine, "announcements")


@router.callback_query(F.data == "menu:help")
async def menu_help(call: CallbackQuery, menu_engine: MenuEngine) -> None:
    await _section_panel(call, menu_engine, "help")


@router.callback_query(F.data == "menu:agents")
async def menu_agents(call: CallbackQuery, state: FSMContext, menu_engine: MenuEngine) -> None:
    lang = _lang(call)
    group_id = await _resolve_agents_group_id(call, state)
    if group_id is None:
        add_group_url = await _group_add_url(call)
        await call.message.edit_text(
            t("no_groups_found", lang),
            reply_markup=menu_engine.empty_group_selector(lang, add_group_url=add_group_url),
        )
        await call.answer()
        return
    await _open_agents_panel(call, state, menu_engine, group_id)


@router.callback_query(F.data == "menu:moderation")
async def menu_moderation(call: CallbackQuery, menu_engine: MenuEngine) -> None:
    lang = _lang(call)
    await call.message.edit_text(
        t("moderation_panel", lang),
        reply_markup=menu_engine.moderation_actions_menu(lang),
    )
    await call.answer()


@router.callback_query(F.data.startswith("groups:"))
async def groups_page(call: CallbackQuery, state: FSMContext, menu_engine: MenuEngine) -> None:
    page = int(call.data.split(":", maxsplit=1)[1])
    async with SessionLocal() as session:
        groups_page_data = await GroupService(session).list_admin_groups(call.from_user.id, page=page, page_size=10)
    lang = _lang(call)
    if groups_page_data.total == 0:
        add_group_url = await _group_add_url(call)
        await call.message.edit_text(
            t("no_groups_found", lang),
            reply_markup=menu_engine.empty_group_selector(lang, add_group_url=add_group_url),
        )
        await call.answer()
        return
    await state.update_data(group_page=page)
    await call.message.edit_reply_markup(reply_markup=menu_engine.group_selector(groups_page_data, lang))
    await call.answer()


@router.callback_query(F.data.startswith("agent-groups:"))
async def agent_groups_page(call: CallbackQuery, state: FSMContext, menu_engine: MenuEngine) -> None:
    page = int(call.data.split(":", maxsplit=1)[1])
    async with SessionLocal() as session:
        groups_page_data = await GroupService(session).list_admin_groups(call.from_user.id, page=page, page_size=10)
    lang = _lang(call)
    if groups_page_data.total == 0:
        add_group_url = await _group_add_url(call)
        await call.message.edit_text(
            t("no_groups_found", lang),
            reply_markup=menu_engine.empty_group_selector(lang, add_group_url=add_group_url),
        )
        await call.answer()
        return
    await state.update_data(group_page=page)
    await call.message.edit_text(
        t("select_group_for_agents", lang),
        reply_markup=menu_engine.agent_group_selector(groups_page_data, lang),
    )
    await call.answer()


@router.callback_query(F.data.startswith("group:") & F.data.endswith(":open"))
async def open_group(call: CallbackQuery, state: FSMContext, menu_engine: MenuEngine, plugin_manager: PluginManager) -> None:
    group_id = int(call.data.split(":")[1])
    async with SessionLocal() as session:
        can_manage = await PermissionService(session).can(group_id, call.from_user.id, "group.settings.update")
    if not can_manage:
        await call.answer(t("permission_denied", _lang(call)), show_alert=True)
        return

    schema = plugin_manager.get_settings_schema()
    categories = sorted({entry.category for entry in schema.values()})
    lang = _lang(call)
    await state.set_state(SettingsFlow.selecting_category)
    await state.update_data(selected_group=group_id)
    await call.message.edit_text(
        t("select_category", lang),
        reply_markup=menu_engine.categories_menu(categories, lang),
    )
    await call.answer()


@router.callback_query(F.data.startswith("agent-group:") & F.data.endswith(":open"))
async def open_agent_group(call: CallbackQuery, state: FSMContext, menu_engine: MenuEngine) -> None:
    group_id = int(call.data.split(":")[1])
    async with SessionLocal() as session:
        can_manage = await PermissionService(session).can(group_id, call.from_user.id, "group.settings.update")
    if not can_manage:
        await call.answer(t("permission_denied", _lang(call)), show_alert=True)
        return
    await _open_agents_panel(call, state, menu_engine, group_id)


@router.callback_query(F.data == "agents:panel")
async def reopen_agents_panel(call: CallbackQuery, state: FSMContext, menu_engine: MenuEngine) -> None:
    data = await state.get_data()
    group_id = data.get("selected_group")
    if group_id is None:
        await menu_agents(call, state, menu_engine)
        return
    await _open_agents_panel(call, state, menu_engine, int(group_id))


@router.callback_query(F.data == "agents:link")
async def agents_link(call: CallbackQuery, state: FSMContext, menu_engine: MenuEngine) -> None:
    data = await state.get_data()
    group_id = data.get("selected_group")
    if group_id is None:
        await menu_agents(call, state, menu_engine)
        return
    lang = _lang(call)
    await state.set_state(SettingsFlow.agents_phone_input)
    await state.update_data(selected_group=int(group_id))
    await call.message.edit_text(t("agent_link_prompt", lang), reply_markup=menu_engine.agents_menu(lang))
    await call.answer()


@router.callback_query(F.data == "agents:list")
async def agents_list(call: CallbackQuery, state: FSMContext, menu_engine: MenuEngine) -> None:
    data = await state.get_data()
    group_id = data.get("selected_group")
    if group_id is None:
        await menu_agents(call, state, menu_engine)
        return
    lang = _lang(call)
    await call.message.edit_text(
        await _agents_list_text(call.from_user.id, int(group_id), lang),
        reply_markup=menu_engine.agents_menu(lang),
    )
    await call.answer()


@router.callback_query(F.data == "agents:jobs")
async def agents_jobs(call: CallbackQuery, state: FSMContext, menu_engine: MenuEngine) -> None:
    data = await state.get_data()
    group_id = data.get("selected_group")
    if group_id is None:
        await menu_agents(call, state, menu_engine)
        return
    lang = _lang(call)
    await state.set_state(SettingsFlow.agents_jobs_menu)
    await state.update_data(selected_group=int(group_id))
    await call.message.edit_text(
        await _agent_jobs_text(call.from_user.id, int(group_id), lang),
        reply_markup=menu_engine.agent_jobs_menu(lang),
    )
    await call.answer()


@router.callback_query(F.data == "agents:create-job")
async def agents_create_job(call: CallbackQuery, state: FSMContext, menu_engine: MenuEngine) -> None:
    data = await state.get_data()
    group_id = data.get("selected_group")
    if group_id is None:
        await menu_agents(call, state, menu_engine)
        return
    lang = _lang(call)
    await state.set_state(SettingsFlow.agents_job_create)
    await state.update_data(selected_group=int(group_id))
    await call.message.edit_text(
        t("agent_jobs_prompt", lang),
        reply_markup=menu_engine.agent_jobs_menu(lang),
    )
    await call.answer()


@router.callback_query(F.data.startswith("category:"))
async def open_category(call: CallbackQuery, state: FSMContext, menu_engine: MenuEngine, plugin_manager: PluginManager) -> None:
    category = call.data.split(":", maxsplit=1)[1]
    data = await state.get_data()
    group_id = data["selected_group"]
    schema = plugin_manager.get_settings_schema()
    schemas = [item for item in schema.values() if item.category == category]

    async with SessionLocal() as session:
        values = await SettingsService(session).get_all(group_id)

    lang = _lang(call)
    await state.set_state(SettingsFlow.editing_setting)
    await state.update_data(selected_category=category)
    await call.message.edit_text(
        t(category, lang),
        reply_markup=menu_engine.settings_for_category(schemas, values, lang),
    )
    await call.answer()


@router.callback_query(F.data == "menu:categories")
async def reopen_categories(call: CallbackQuery, state: FSMContext, menu_engine: MenuEngine, plugin_manager: PluginManager) -> None:
    data = await state.get_data()
    group_id = data["selected_group"]
    async with SessionLocal() as session:
        can_manage = await PermissionService(session).can(group_id, call.from_user.id, "group.settings.update")
    if not can_manage:
        await call.answer(t("permission_denied", _lang(call)), show_alert=True)
        return
    schema = plugin_manager.get_settings_schema()
    categories = sorted({entry.category for entry in schema.values()})
    lang = _lang(call)
    await state.set_state(SettingsFlow.selecting_category)
    await call.message.edit_text(
        t("select_category", lang),
        reply_markup=menu_engine.categories_menu(categories, lang),
    )
    await call.answer()


@router.callback_query(F.data.startswith("setting:") & F.data.endswith(":toggle"))
async def toggle_setting(call: CallbackQuery, state: FSMContext, menu_engine: MenuEngine, plugin_manager: PluginManager) -> None:
    key = call.data.split(":")[1]
    data = await state.get_data()
    group_id = data["selected_group"]
    category = data["selected_category"]
    schema_map = plugin_manager.get_settings_schema()

    async with SessionLocal() as session:
        can_manage = await PermissionService(session).can(group_id, call.from_user.id, "group.settings.update")
        if not can_manage:
            await call.answer(t("permission_denied", _lang(call)), show_alert=True)
            return
        service = SettingsService(session)
        current = await service.get_one(group_id, key)
        await service.set_value(group_id, key, not bool(current))
        values = await service.get_all(group_id)

    schemas = [entry for entry in schema_map.values() if entry.category == category]
    lang = _lang(call)
    await call.message.edit_reply_markup(reply_markup=menu_engine.settings_for_category(schemas, values, lang))
    await call.answer()


@router.callback_query(F.data.startswith("setting:") & F.data.endswith(":slider"))
async def open_slider(call: CallbackQuery, state: FSMContext, menu_engine: MenuEngine, plugin_manager: PluginManager) -> None:
    key = call.data.split(":")[1]
    schema = plugin_manager.get_settings_schema()[key]
    data = await state.get_data()
    group_id = data["selected_group"]

    async with SessionLocal() as session:
        current = await SettingsService(session).get_one(group_id, key)
    current_value = int(current if current is not None else schema.default or 0)
    lang = _lang(call)

    await call.message.edit_text(
        f"{t(schema.label_key, lang)}\n\n{t('current', lang)}: {current_value}",
        reply_markup=menu_engine.numeric_slider(schema, current_value, lang),
    )
    await call.answer()


@router.callback_query(F.data.startswith("slider:"))
async def apply_slider(call: CallbackQuery, state: FSMContext, menu_engine: MenuEngine, plugin_manager: PluginManager) -> None:
    _, key, value = call.data.split(":")
    next_value = int(value)
    data = await state.get_data()
    group_id = data["selected_group"]
    schema = plugin_manager.get_settings_schema()[key]
    lang = _lang(call)

    async with SessionLocal() as session:
        can_manage = await PermissionService(session).can(group_id, call.from_user.id, "group.settings.update")
        if not can_manage:
            await call.answer(t("permission_denied", lang), show_alert=True)
            return
        await SettingsService(session).set_value(group_id, key, next_value)

    await call.message.edit_text(
        f"{t(schema.label_key, lang)}\n\n{t('current', lang)}: {next_value}",
        reply_markup=menu_engine.numeric_slider(schema, next_value, lang),
    )
    await call.answer()


@router.callback_query(F.data == "menu:category")
async def reopen_category(call: CallbackQuery, state: FSMContext, menu_engine: MenuEngine, plugin_manager: PluginManager) -> None:
    data = await state.get_data()
    group_id = data["selected_group"]
    category = data["selected_category"]
    schema_map = plugin_manager.get_settings_schema()
    schemas = [entry for entry in schema_map.values() if entry.category == category]
    async with SessionLocal() as session:
        values = await SettingsService(session).get_all(group_id)
    lang = _lang(call)
    await call.message.edit_text(
        t(category, lang),
        reply_markup=menu_engine.settings_for_category(schemas, values, lang),
    )
    await call.answer()


@router.callback_query(F.data == "noop")
async def noop(call: CallbackQuery) -> None:
    await call.answer()


@router.callback_query(F.data.startswith("quick:"))
async def quick_action_prompt(call: CallbackQuery, state: FSMContext, menu_engine: MenuEngine) -> None:
    _, action, user_id = call.data.split(":")
    await state.update_data(moderation_target_user_id=int(user_id))
    lang = _lang(call)
    await call.message.edit_text(
        f"⚠️ {t('confirm_action', lang)}: {action} @{user_id}",
        reply_markup=menu_engine.confirmation_menu(action, int(user_id), lang),
    )
    await call.answer()


@router.callback_query(F.data.startswith("mod:"))
async def moderation_action_prompt(call: CallbackQuery, state: FSMContext, menu_engine: MenuEngine) -> None:
    action = call.data.split(":", maxsplit=1)[1]
    lang = _lang(call)
    data = await state.get_data()
    target_user_id = int(data.get("moderation_target_user_id", 0) or 0)
    if action in MOD_USER_ACTIONS and target_user_id <= 0:
        await call.answer(t("select_user_first", lang), show_alert=True)
        return
    await call.message.edit_text(
        f"⚠️ {t('confirm_action', lang)}: {action}",
        reply_markup=menu_engine.confirmation_menu(action, target_user_id, lang),
    )
    await call.answer()


@router.callback_query(F.data.startswith("confirm:"))
async def moderation_action_confirm(call: CallbackQuery, state: FSMContext, menu_engine: MenuEngine) -> None:
    _, action, target_raw = call.data.split(":")
    target_user_id = int(target_raw)
    lang = _lang(call)

    resolved = await _resolve_moderation_group(call, state)
    if not resolved:
        await call.answer(t("no_groups_found", lang), show_alert=True)
        return
    group_id, tg_group_id = resolved

    required_permission = MOD_PERMISSION_MAP.get(action, "group.settings.update")
    async with SessionLocal() as session:
        allowed = await PermissionService(session).can(group_id, call.from_user.id, required_permission)
        if not allowed:
            await call.answer(t("permission_denied", lang), show_alert=True)
            return

        executed_on_telegram = True
        details: dict[str, object] = {"source": "inline_moderation_menu"}

        if action in {"anti_links", "anti_spam", "anti_ads"}:
            service = SettingsService(session)
            current = await service.get_one(group_id, action)
            next_value = not bool(current)
            await service.set_value(group_id, action, next_value)
            details["enabled"] = next_value
            log_action = f"toggle_{action}"
        elif action == "warn":
            if target_user_id <= 0:
                await call.answer(t("select_user_first", lang), show_alert=True)
                return
            group = (await session.execute(select(Group).where(Group.id == group_id))).scalar_one()
            warning = await add_warning(
                session,
                group_id=group_id,
                user_id=target_user_id,
                issued_by=call.from_user.id,
                reason="manual_warn",
                count=1,
            )
            remove_limit = await maybe_remove_user_on_warning_limit(
                session,
                group=group,
                bot=call.bot,
                user_id=target_user_id,
                admin_user_id=call.from_user.id,
                warning=warning,
                reason="manual_warn",
                details={"source": "inline_moderation_menu"},
            )
            mute_limit = await maybe_mute_user_on_warning_limit(
                session,
                group=group,
                bot=call.bot,
                user_id=target_user_id,
                admin_user_id=call.from_user.id,
                warning=warning,
                reason="manual_warn",
                details={"source": "inline_moderation_menu"},
            )
            if remove_limit is not None:
                details["warn_limit"] = remove_limit
            if mute_limit is not None:
                details["mute_limit"] = mute_limit
            log_action = "warn_user"
        elif action == "ban":
            if target_user_id <= 0:
                await call.answer(t("select_user_first", lang), show_alert=True)
                return
            try:
                await call.bot.ban_chat_member(chat_id=tg_group_id, user_id=target_user_id)
            except Exception as exc:
                executed_on_telegram = False
                details["error"] = str(exc)
            log_action = "ban_user"
        elif action == "mute":
            if target_user_id <= 0:
                await call.answer(t("select_user_first", lang), show_alert=True)
                return
            try:
                await call.bot.restrict_chat_member(
                    chat_id=tg_group_id,
                    user_id=target_user_id,
                    permissions=ChatPermissions(can_send_messages=False),
                )
            except Exception as exc:
                executed_on_telegram = False
                details["error"] = str(exc)
            log_action = "mute_user"
        else:
            # clean and future moderation actions are still audit-logged.
            log_action = "clean_requested"

        details["telegram_applied"] = executed_on_telegram
        session.add(
            ModerationLog(
                group_id=group_id,
                action=log_action,
                target_user_id=target_user_id or None,
                admin_user_id=call.from_user.id,
                reason="manual_moderation",
                details=details,
            )
        )
        await session.commit()

    await call.message.edit_text(
        t("action_completed", lang) if details["telegram_applied"] else t("action_logged_only", lang),
        reply_markup=menu_engine.moderation_actions_menu(lang),
    )
    await call.answer()
