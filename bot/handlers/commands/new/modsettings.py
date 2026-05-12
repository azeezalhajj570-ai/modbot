from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.db.session import SessionLocal
from bot.services.group_service import GroupService
from bot.services.moderation_settings_service import ModerationSettingsService
from bot.services.settings_service import SettingsService
from bot.utils.i18n import t

from ._shared import group_picker_keyboard, resolve_lang

router = Router(name="cmd_modsettings")


class ModSettingsFlow(StatesGroup):
    selecting_group = State()
    waiting_value = State()


AI_ACTIONS = {
    "action_for_arabic_ads": "Arabic Ads",
    "action_for_investment_scam": "Investment Scam",
    "action_for_crypto_scam": "Crypto Scam",
    "action_for_phishing_link": "Phishing Links",
    "action_for_link_spam": "Link Spam",
    "action_for_repeated_promo": "Repeated Promo",
}

ACTION_OPTIONS = ["allow", "review", "delete", "warn", "mute", "ban"]

OTHER_SETTINGS = {
    "muted_duration_seconds": ("int", t("modsettings_mute_duration", "en")),
    "max_messages_per_minute": ("int", t("modsettings_rate_limits", "en")),
    "notify_on_violation": ("bool", "Notify on Violations"),
    "notify_on_join": ("bool", "Notify on Join"),
    "welcome_enabled": ("bool", t("modsettings_welcome", "en")),
    "ban_after_delete": ("bool", t("modsettings_ban_delete", "en")),
}


async def get_user_groups(message) -> list[dict]:
    uid = message.from_user.id if hasattr(message, "from_user") and message.from_user else 0
    async with SessionLocal() as session:
        return await GroupService(session).list_admin_groups_all(uid)


async def _render_modsettings(message: Message, group_id: int, lang: str, edit: bool = False) -> None:
    async with SessionLocal() as session:
        ai_settings = await ModerationSettingsService(session).get_settings(group_id)
        svc = SettingsService(session)
        warn_auto_mute = bool(await svc.get_one(group_id, "warn_auto_mute") or False)
        warn_auto_remove = bool(await svc.get_one(group_id, "warn_auto_remove") or False)

    text = f"🛡 *{t('modsettings_title', lang)}*\n\n*{t('modsettings_ai_actions', lang)}:*\n"
    for key, label in AI_ACTIONS.items():
        val = ai_settings.get(key, "none")
        text += f"• {label}: `{val}`\n"

    text += f"\n*{t('modsettings_mute_duration', lang)}:* {ai_settings.get('muted_duration_seconds', 3600)}s\n"
    text += f"🔇 {t('warnings_auto_mute', lang)}: {'✅' if warn_auto_mute else '❌'}\n"
    text += f"🚫 {t('warnings_auto_ban', lang)}: {'✅' if warn_auto_remove else '❌'}\n"

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=f"⬅ {t('back', lang)}", callback_data="cmd:menu"),
        InlineKeyboardButton(text=f"🔄 {t('refresh', lang)}", callback_data=f"msr:{group_id}"),
    )

    if edit:
        await message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    else:
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.message(Command("modsettings"))
async def modsettings_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    lang = await resolve_lang(message)
    groups = await get_user_groups(message)
    if not groups:
        await message.answer(t("no_groups_found", lang))
        return
    if len(groups) == 1:
        await _render_modsettings(message, groups[0]["id"], lang)
    else:
        await state.set_state(ModSettingsFlow.selecting_group)
        await message.answer(t("select_group", lang), reply_markup=group_picker_keyboard(groups, lang))


@router.callback_query(ModSettingsFlow.selecting_group, F.data.startswith("cg:"))
async def modsettings_group_chosen(call: CallbackQuery, state: FSMContext) -> None:
    group_id = int(call.data.split(":")[1])
    lang = await resolve_lang(call.message)
    await state.clear()
    await _render_modsettings(call.message, group_id, lang, edit=True)
    await call.answer()


@router.callback_query(F.data.startswith("gp:"))
async def modsettings_group_page(call: CallbackQuery) -> None:
    page = int(call.data.split(":")[1])
    lang = await resolve_lang(call.message)
    groups = await get_user_groups(call.message)
    if groups:
        await call.message.edit_text(t("select_group", lang), reply_markup=group_picker_keyboard(groups, lang, page=page))
    await call.answer()


@router.callback_query(F.data.startswith("msr:"))
async def modsettings_refresh(call: CallbackQuery) -> None:
    group_id = int(call.data.split(":")[1])
    lang = await resolve_lang(call.message)
    await _render_modsettings(call.message, group_id, lang, edit=True)
    await call.answer()
