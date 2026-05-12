from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup

from bot.db.session import SessionLocal
from bot.services.admin_activity_service import AdminActivityService
from bot.services.group_service import GroupService
from bot.utils.i18n import t

from ._shared import group_picker_keyboard, resolve_lang, back_button

router = Router(name="cmd_stats")


class StatsFlow(StatesGroup):
    selecting_group = State()


@router.message(Command("stats"))
async def stats_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    lang = await resolve_lang(message)
    groups = await get_user_groups(message)
    if not groups:
        await message.answer(t("no_groups_found", lang))
        return
    if len(groups) == 1:
        await show_stats(message, groups[0]["id"], lang)
    else:
        await state.set_state(StatsFlow.selecting_group)
        await message.answer(t("select_group_for_analytics", lang), reply_markup=group_picker_keyboard(groups, lang))


async def get_user_groups(message: Message) -> list[dict]:
    if not message.from_user:
        return []
    async with SessionLocal() as session:
        return await GroupService(session).list_admin_groups_all(message.from_user.id)


async def show_stats(message: Message, group_id: int, lang: str, edit: bool = False) -> None:
    async with SessionLocal() as session:
        overview = await AdminActivityService(session).build_group_overview(group_id=group_id)
    stats = overview.get("stats", {})
    recent = overview.get("recent_actions", [])
    group_info = overview.get("group", {})
    health = _compute_health(stats)

    text = (
        f"📊 *{group_info.get('title', 'Group')}*\n"
        f"{t('dashboard', lang)}:\n\n"
        f"🟢 *{t('dashboard_health', lang)}*: {health}\n"
        f"📨 {t('dashboard_msgs_tracked', lang)}: {stats.get('messages_count', 0)}\n"
        f"⚠️ {t('dashboard_spam_detected', lang)}: {stats.get('spam_detected', 0)}\n"
        f"🗑 {t('dashboard_msgs_deleted', lang)}: {stats.get('messages_deleted', 0)}\n"
        f"👥 {t('dashboard_active_members', lang)}: {stats.get('members_count', 0)}\n\n"
        f"👤 {t('dashboard_moderators', lang)}: {stats.get('active_moderators', 0)}\n"
        f"⚠️ {t('dashboard_warnings', lang)}: {stats.get('total_warnings', 0)}\n"
        f"🔌 {t('dashboard_plugins', lang)}: {stats.get('enabled_plugins', 0)}\n"
        f"⚙️ {t('dashboard_settings_conf', lang)}: {stats.get('configured_settings', 0)}\n"
    )

    if recent:
        text += f"\n*{t('dashboard_recent_actions', lang)}:*\n"
        for r in recent[:5]:
            action = r.get("action", "?")
            when = (r.get("created_at") or "")[:16]
            text += f"• {action} ({when})\n"

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=f"🔄 {t('refresh', lang)}", callback_data=f"stats:{group_id}"))
    builder.row(InlineKeyboardButton(text=f"⬅ {t('back', lang)}", callback_data="cmd:menu"))

    if edit:
        await message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    else:
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")


def _compute_health(stats: dict) -> str:
    spam = stats.get("spam_detected", 0)
    deleted = stats.get("messages_deleted", 0)
    warnings = stats.get("total_warnings", 0)
    score = 100
    if spam > 50:
        score -= 20
    if deleted > 20:
        score -= 10
    if warnings > 10:
        score -= 15
    if score >= 80:
        return "🟢 Healthy"
    elif score >= 50:
        return "🟡 Needs Attention"
    return "🔴 At Risk"


@router.callback_query(F.data.startswith("stats:"))
async def stats_refresh(call: CallbackQuery) -> None:
    group_id = int(call.data.split(":")[1])
    lang = await resolve_lang(call.message)
    await show_stats(call.message, group_id, lang, edit=True)
    await call.answer()


@router.callback_query(StatsFlow.selecting_group, F.data.startswith("cg:"))
async def stats_group_chosen(call: CallbackQuery, state: FSMContext) -> None:
    group_id = int(call.data.split(":")[1])
    lang = await resolve_lang(call.message)
    await state.clear()
    await show_stats(call.message, group_id, lang, edit=True)
    await call.answer()


@router.callback_query(F.data.startswith("gp:"))
async def stats_group_page(call: CallbackQuery) -> None:
    page = int(call.data.split(":")[1])
    lang = await resolve_lang(call.message)
    groups = await get_user_groups(call.message)
    if groups:
        await call.message.edit_text(t("select_group_for_analytics", lang), reply_markup=group_picker_keyboard(groups, lang, page=page))
    await call.answer()
