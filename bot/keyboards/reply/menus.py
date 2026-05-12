from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, WebAppInfo

from bot.config import AppKind, get_settings
from bot.schemas.settings import SettingSchema, SettingType
from bot.services.menu_button_service import resolve_webapp_url
from bot.utils.i18n import t
from bot.utils.pagination import Page


def tab_rows(lang: str) -> list[list[str]]:
    return [
        [f"👥 {t('members', lang)}", f"🤖 {t('agents', lang)}"],
        [f"🌐 {t('language', lang)}", f"❓ {t('help', lang)}"],
    ]


def _reply(rows: list[list[str]]) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=cell) for cell in row] for row in rows],
        resize_keyboard=True,
        is_persistent=True,
    )

def _open_app_button_label(lang: str, app_kind: AppKind) -> str:
    if app_kind == "agents":
        return f"🤖 {t('open_agents_miniapp', lang)}"
    return f"📋 {t('open_admin_miniapp', lang)}"


def main_menu_keyboard(
    lang: str,
    dashboard_url: str | None = None,
    *,
    app_kind: AppKind | None = None,
) -> ReplyKeyboardMarkup:
    return ReplyKeyboardRemove()


def group_management_menu_keyboard(lang: str, include_tabs: bool = True) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = []
    if include_tabs:
        rows.extend(tab_rows(lang))
    rows.extend([
        [f"🛡 {t('moderation_panel', lang)}"],
        [f"👥 {t('members', lang)}"],
        [f"📊 {t('stats', lang)}"],
        [f"🏠 {t('main_menu_btn', lang)}"],
        [f"⬅ {t('back', lang)}"],
    ])
    return _reply(rows)


def empty_groups_keyboard(lang: str, include_tabs: bool = True) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = []
    if include_tabs:
        rows.extend(tab_rows(lang))
    rows.extend([
        [f"➕ {t('add_group', lang)}"],
        [f"🔄 {t('refresh', lang)}"],
        [f"⬅ {t('back', lang)}"],
    ])
    return _reply(rows)


def groups_keyboard(groups: Page[dict], lang: str, include_tabs: bool = True) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = []
    if include_tabs:
        rows.extend(tab_rows(lang))
    rows.extend([[item["title"]] for item in groups.items])

    nav_row: list[str] = []
    if groups.has_prev:
        nav_row.append(f"◀ {t('prev', lang)}")
    nav_row.append(f"{t('page', lang)} {groups.page}/{groups.pages}")
    if groups.has_next:
        nav_row.append(f"{t('next', lang)} ▶")
    rows.append(nav_row)
    rows.append([f"🔄 {t('refresh', lang)}"])
    rows.append([f"⬅ {t('back', lang)}"])
    return _reply(rows)


def categories_keyboard(categories: list[str], lang: str, include_tabs: bool = True) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = []
    if include_tabs:
        rows.extend(tab_rows(lang))
    rows.extend([[t(category, lang)] for category in categories])
    rows.append([f"⬅ {t('back', lang)}"])
    return _reply(rows)


def settings_keyboard(
    schemas: list[SettingSchema],
    values: dict[str, bool | int | str],
    lang: str,
    include_tabs: bool = True,
) -> tuple[ReplyKeyboardMarkup, dict[str, tuple[str, str]]]:
    rows: list[list[str]] = []
    if include_tabs:
        rows.extend(tab_rows(lang))
    mapping: dict[str, tuple[str, str]] = {}

    for schema in schemas:
        value = values.get(schema.key, schema.default)
        if schema.type == SettingType.TOGGLE:
            state = t("enabled", lang) if value else t("disabled", lang)
            title = f"{t(schema.label_key, lang)}: {state}"
            rows.append([title])
            mapping[title] = (schema.key, schema.type.value)
        elif schema.type == SettingType.NUMBER:
            title = f"{t(schema.label_key, lang)}: {value}"
            rows.append([title])
            mapping[title] = (schema.key, schema.type.value)

    rows.append([f"⬅ {t('back', lang)}"])
    return _reply(rows), mapping


def slider_keyboard(lang: str, include_tabs: bool = True) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = []
    if include_tabs:
        rows.extend(tab_rows(lang))
    rows.extend([
        ["-1", "+1"],
        [f"⬅ {t('back', lang)}"],
    ])
    return _reply(rows)


def moderation_menu_keyboard(
    lang: str,
    include_tabs: bool = True,
    toggle_states: dict[str, bool] | None = None,
) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = []
    if include_tabs:
        rows.extend(tab_rows(lang))
    toggle_states = toggle_states or {}
    def toggle_label(key: str, icon: str) -> str:
        state = t("on", lang) if toggle_states.get(key, True) else t("off", lang)
        return f"{icon} {t(key, lang)}: {state}"
    rows.extend([
        [f"📄 {t('warnings_summary', lang)}"],
        [f"🧾 {t('recent_actions', lang)}"],
        [toggle_label("anti_links", "🔗")],
        [toggle_label("anti_spam", "🚨")],
        [toggle_label("anti_ads", "📣")],
        [toggle_label("anti_spam_mute", "🔇")],
        [toggle_label("anti_ads_mute", "🔕")],
        [toggle_label("warn_auto_remove", "🚪")],
        [toggle_label("anti_bots", "🤖")],
        [f"🔐 {t('access_gate', lang)}"],
        [toggle_label("join_request_verify", "📋")],
        [f"🗑 {t('reset_warnings', lang)}"],
        [f"🌐 {t('language', lang)}"],
        [f"🏠 {t('main_menu_btn', lang)}"],
        [f"⬅ {t('back', lang)}"],
    ])
    return _reply(rows)


def members_menu_keyboard(lang: str, include_tabs: bool = True) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = []
    if include_tabs:
        rows.extend(tab_rows(lang))
    rows.extend([
        [f"👑 {t('admin_list', lang)}"],
        [f"👥 {t('member_list', lang)}"],
        [f"➕ {t('promote', lang)}"],
        [f"➖ {t('demote', lang)}"],
        [f"🔎 {t('search_user', lang)}"],
        [f"🌐 {t('language', lang)}"],
        [f"🏠 {t('main_menu_btn', lang)}"],
        [f"⬅ {t('back', lang)}"],
    ])
    return _reply(rows)


def plugins_menu_keyboard(plugin_states: dict[str, bool], lang: str, include_tabs: bool = True) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = []
    if include_tabs:
        rows.extend(tab_rows(lang))
    for name, enabled in sorted(plugin_states.items()):
        mark = "✅" if enabled else "❌"
        rows.append([f"{mark} {name}"])
    rows.append([f"🔄 {t('refresh', lang)}"])
    rows.append([f"🌐 {t('language', lang)}"])
    rows.append([f"🏠 {t('main_menu_btn', lang)}"])
    rows.append([f"⬅ {t('back', lang)}"])
    return _reply(rows)


def analytics_menu_keyboard(lang: str, include_tabs: bool = True) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = []
    if include_tabs:
        rows.extend(tab_rows(lang))
    rows.extend([
        [f"📈 {t('refresh_analytics', lang)}"],
        [f"🌐 {t('language', lang)}"],
        [f"🏠 {t('main_menu_btn', lang)}"],
        [f"⬅ {t('back', lang)}"],
    ])
    return _reply(rows)


def announcements_menu_keyboard(lang: str, include_tabs: bool = True) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = []
    if include_tabs:
        rows.extend(tab_rows(lang))
    rows.extend([
        [f"🗓 {t('schedule_message', lang)}"],
        [f"📚 {t('view_scheduled_messages', lang)}"],
        [f"✏️ {t('edit_scheduled_message', lang)}"],
        [f"🗑 {t('delete_scheduled_message', lang)}"],
        [f"🚀 {t('send_due_messages', lang)}"],
        [f"🧩 {t('select_bulk_groups', lang)}"],
        [f"📨 {t('send_bulk_message', lang)}"],
        [f"🌐 {t('language', lang)}"],
        [f"🏠 {t('main_menu_btn', lang)}"],
        [f"⬅ {t('back', lang)}"],
    ])
    return _reply(rows)


def tasks_menu_keyboard(lang: str, include_tabs: bool = True) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = []
    if include_tabs:
        rows.extend(tab_rows(lang))
    rows.extend([
        [f"➕ {t('add_reply_task', lang)}"],
        [f"📣 {t('add_notify_task', lang)}"],
        [f"📋 {t('task_catalog', lang)}"],
        [f"🧩 {t('task_assignments', lang)}"],
        [f"🗑 {t('delete_task', lang)}"],
        [f"🏠 {t('main_menu_btn', lang)}"],
        [f"⬅ {t('back', lang)}"],
    ])
    return _reply(rows)


def task_executor_keyboard(lang: str, include_tabs: bool = True) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = []
    if include_tabs:
        rows.extend(tab_rows(lang))
    rows.extend([
        [f"🤖 {t('task_executor_bot', lang)}"],
        [f"👤 {t('task_executor_agent', lang)}"],
        [f"⬅ {t('back', lang)}"],
    ])
    return _reply(rows)


def task_agent_keyboard(agent_labels: list[str], lang: str, include_tabs: bool = True) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = []
    if include_tabs:
        rows.extend(tab_rows(lang))
    rows.extend([[label] for label in agent_labels])
    rows.append([f"⬅ {t('back', lang)}"])
    return _reply(rows)


def task_group_keyboard(group_labels: Page[str], lang: str, include_tabs: bool = True) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = []
    if include_tabs:
        rows.extend(tab_rows(lang))
    rows.extend([[label] for label in group_labels.items])
    nav_row: list[str] = []
    if group_labels.has_prev:
        nav_row.append(f"◀ {t('prev', lang)}")
    nav_row.append(f"{t('page', lang)} {group_labels.page}/{group_labels.pages}")
    if group_labels.has_next:
        nav_row.append(f"{t('next', lang)} ▶")
    rows.append(nav_row)
    rows.append([f"⬅ {t('back', lang)}"])
    return _reply(rows)


def task_reply_visibility_keyboard(lang: str, include_tabs: bool = True) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = []
    if include_tabs:
        rows.extend(tab_rows(lang))
    rows.extend([
        [f"🌐 {t('task_reply_public', lang)}"],
        [f"🔒 {t('task_reply_private', lang)}"],
        [f"⬅ {t('back', lang)}"],
    ])
    return _reply(rows)


def task_notify_delivery_mode_keyboard(lang: str, include_tabs: bool = True) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = []
    if include_tabs:
        rows.extend(tab_rows(lang))
    rows.extend([
        [f"📝 {t('task_notify_mode_text', lang)}"],
        [f"↪️ {t('task_notify_mode_forward', lang)}"],
        [f"📋 {t('task_notify_mode_copy', lang)}"],
        [f"📝↪️ {t('task_notify_mode_text_and_forward', lang)}"],
        [f"📝📋 {t('task_notify_mode_text_and_copy', lang)}"],
        [f"⬅ {t('back', lang)}"],
    ])
    return _reply(rows)


def task_delete_keyboard(task_labels: list[str], lang: str, include_tabs: bool = True) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = []
    if include_tabs:
        rows.extend(tab_rows(lang))
    rows.extend([[label] for label in task_labels])
    rows.append([f"⬅ {t('back', lang)}"])
    return _reply(rows)


def task_delete_confirm_keyboard(lang: str, include_tabs: bool = True) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = []
    if include_tabs:
        rows.extend(tab_rows(lang))
    rows.extend([
        [f"✅ {t('confirm', lang)}"],
        [f"⬅ {t('back', lang)}"],
    ])
    return _reply(rows)


def agents_menu_keyboard(lang: str, include_tabs: bool = True) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = []
    if include_tabs:
        rows.extend(tab_rows(lang))
    rows.extend([
        [f"🔗 {t('link_account', lang)}"],
        [f"📋 {t('my_agents', lang)}"],
        [f"⚙ {t('agent_jobs', lang)}"],
        [f"🏠 {t('main_menu_btn', lang)}"],
        [f"⬅ {t('back', lang)}"],
    ])
    return _reply(rows)


def agent_list_keyboard(agent_labels: list[str], lang: str, include_tabs: bool = True) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = []
    if include_tabs:
        rows.extend(tab_rows(lang))
    rows.append([f"🔗 {t('link_account', lang)}"])
    rows.extend([[label] for label in agent_labels])
    rows.extend([
        [f"🏠 {t('main_menu_btn', lang)}"],
        [f"⬅ {t('back', lang)}"],
    ])
    return _reply(rows)


def agent_actions_keyboard(lang: str, include_tabs: bool = True) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = []
    if include_tabs:
        rows.extend(tab_rows(lang))
    rows.extend([
        [f"⚙ {t('agent_jobs', lang)}"],
        [f"➕ {t('create_job', lang)}"],
        [f"🔌 {t('unlink_account', lang)}"],
        [f"🏠 {t('main_menu_btn', lang)}"],
        [f"⬅ {t('back', lang)}"],
    ])
    return _reply(rows)


def agent_unlink_confirm_keyboard(lang: str, include_tabs: bool = True) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = []
    if include_tabs:
        rows.extend(tab_rows(lang))
    rows.extend([
        [f"✅ {t('confirm', lang)}"],
        [f"⬅ {t('back', lang)}"],
    ])
    return _reply(rows)


def agent_jobs_menu_keyboard(lang: str, include_tabs: bool = True) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = []
    if include_tabs:
        rows.extend(tab_rows(lang))
    rows.extend([
        [f"➕ {t('create_job', lang)}"],
        [f"🏠 {t('main_menu_btn', lang)}"],
        [f"⬅ {t('back', lang)}"],
    ])
    return _reply(rows)


def bulk_groups_keyboard(
    groups: list[dict],
    selected_group_ids: set[int],
    lang: str,
    include_tabs: bool = True,
) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = []
    if include_tabs:
        rows.extend(tab_rows(lang))
    for group in groups:
        mark = "✅" if int(group["id"]) in selected_group_ids else "☑"
        rows.append([f"{mark} {group['title']}"])
    rows.extend([
        [f"🧹 {t('clear_selected_groups', lang)}"],
        [f"📨 {t('send_bulk_message', lang)}"],
        [f"🌐 {t('language', lang)}"],
        [f"🏠 {t('main_menu_btn', lang)}"],
        [f"⬅ {t('back', lang)}"],
    ])
    return _reply(rows)


def help_menu_keyboard(lang: str, include_tabs: bool = True) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = []
    if include_tabs:
        rows.extend(tab_rows(lang))
    rows.extend([
        [f"📘 {t('help_overview', lang)}"],
        [f"⌨ {t('help_commands', lang)}"],
        [f"🧭 {t('help_panels', lang)}"],
        [f"📢 {t('help_announcements', lang)}"],
        [f"🌐 {t('language', lang)}"],
        [f"🏠 {t('main_menu_btn', lang)}"],
        [f"⬅ {t('back', lang)}"],
    ])
    return _reply(rows)


def access_gate_keyboard(
    candidates: list[dict],
    selected_tg_group_ids: set[int],
    lang: str,
    include_tabs: bool = True,
) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = []
    if include_tabs:
        rows.extend(tab_rows(lang))
    for group in candidates:
        tg_id = int(group["tg_group_id"])
        mark = "✅" if tg_id in selected_tg_group_ids else "☑"
        rows.append([f"{mark} {group['title']}"])
    rows.append([f"🧹 {t('clear_required_groups', lang)}"])
    rows.append([f"🌐 {t('language', lang)}"])
    rows.append([f"🏠 {t('main_menu_btn', lang)}"])
    rows.append([f"⬅ {t('back', lang)}"])
    return _reply(rows)


def language_keyboard(lang: str) -> ReplyKeyboardMarkup:
    return _reply([
        *tab_rows(lang),
        [f"🇺🇸 {t('language_en', lang)}"],
        [f"🇸🇦 {t('language_ar', lang)}"],
        [f"⬅ {t('back', lang)}"],
    ])
