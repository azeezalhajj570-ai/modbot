from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import get_settings
from bot.db.session import SessionLocal
from bot.services.group_service import GroupService
from bot.services.user_service import UserService
from bot.utils.i18n import t

from ._shared import resolve_lang

router = Router(name="cmd_menu")


def cmd_keyboard(lang: str, is_owner: bool = False) -> InlineKeyboardMarkup:
    return _menu_keyboard(lang, is_owner=is_owner)


def _menu_keyboard(lang: str, is_owner: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=f"📊 {t('dashboard', lang)}", callback_data="cmd:stats"),
        InlineKeyboardButton(text=f"🛡 {t('moderation', lang)}", callback_data="cmd:modsettings"),
    )
    builder.row(
        InlineKeyboardButton(text=f"✅ {t('tasks', lang)}", callback_data="cmd:tasks"),
        InlineKeyboardButton(text=f"📢 {t('announcements', lang)}", callback_data="cmd:schedule"),
    )
    builder.row(
        InlineKeyboardButton(text=f"⚠️ {t('events_title', lang)}", callback_data="cmd:events"),
        InlineKeyboardButton(text=f"🔇 {t('restricted_title', lang)}", callback_data="cmd:restricted"),
    )
    builder.row(
        InlineKeyboardButton(text=f"📋 {t('warnings', lang)}", callback_data="cmd:warnings"),
        InlineKeyboardButton(text=f"🚪 {t('access_gate', lang)}", callback_data="cmd:accessgate"),
    )
    if is_owner:
        builder.row(InlineKeyboardButton(text=f"💳 {t('subscriptions', lang)}", callback_data="cmd:subscriptions"))
    builder.row(
        InlineKeyboardButton(text=f"❓ {t('help', lang)}", callback_data="cmd:help"),
        InlineKeyboardButton(text=f"🌐 {t('language', lang)}", callback_data="cmd:lang"),
    )
    return builder.as_markup()


@router.message(Command("menu"))
async def menu_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    lang = await resolve_lang(message)
    settings = get_settings()
    is_owner = message.from_user and message.from_user.id in set(settings.bot_owner_ids)
    await message.answer(
        t("main_menu", lang),
        reply_markup=_menu_keyboard(lang, is_owner=is_owner),
    )


@router.callback_query(F.data == "cmd:menu")
async def menu_callback(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    lang = await resolve_lang(call.message)
    settings = get_settings()
    is_owner = call.from_user and call.from_user.id in set(settings.bot_owner_ids)
    await call.message.edit_text(
        t("main_menu", lang),
        reply_markup=_menu_keyboard(lang, is_owner=is_owner),
    )
    await call.answer()


@router.callback_query(F.data == "cmd:stats")
async def nav_stats(call: CallbackQuery, state: FSMContext) -> None:
    from .stats import stats_handler
    await stats_handler(call.message, state)


@router.callback_query(F.data == "cmd:events")
async def nav_events(call: CallbackQuery, state: FSMContext) -> None:
    from .events import events_handler
    await events_handler(call.message, state)


@router.callback_query(F.data == "cmd:restricted")
async def nav_restricted(call: CallbackQuery, state: FSMContext) -> None:
    from .restricted import restricted_handler
    await restricted_handler(call.message, state)


@router.callback_query(F.data == "cmd:modsettings")
async def nav_modsettings(call: CallbackQuery, state: FSMContext) -> None:
    from .modsettings import modsettings_handler
    await modsettings_handler(call.message, state)


@router.callback_query(F.data == "cmd:warnings")
async def nav_warnings(call: CallbackQuery, state: FSMContext) -> None:
    from .warnings import warnings_handler
    await warnings_handler(call.message, state)


@router.callback_query(F.data == "cmd:accessgate")
async def nav_accessgate(call: CallbackQuery, state: FSMContext) -> None:
    from .accessgate import accessgate_handler
    await accessgate_handler(call.message, state)


@router.callback_query(F.data == "cmd:schedule")
async def nav_schedule(call: CallbackQuery, state: FSMContext) -> None:
    from .schedule import schedule_handler
    await schedule_handler(call.message, state)


@router.callback_query(F.data == "cmd:tasks")
async def nav_tasks(call: CallbackQuery, state: FSMContext) -> None:
    from .task import task_handler
    await task_handler(call.message, state)


@router.callback_query(F.data == "cmd:subscriptions")
async def nav_subscriptions(call: CallbackQuery, state: FSMContext) -> None:
    from .subscriptions import subscriptions_handler
    await subscriptions_handler(call.message, state)


@router.callback_query(F.data == "cmd:help")
async def help_callback(call: CallbackQuery) -> None:
    lang = await resolve_lang(call.message)
    text = (
        f"/menu - {t('main_menu', lang)}\n"
        f"/stats - {t('dashboard', lang)}\n"
        f"/events - {t('events_title', lang)}\n"
        f"/restricted - {t('restricted_title', lang)}\n"
        f"/task - {t('tasks', lang)}\n"
        f"/schedule - {t('announcements', lang)}\n"
        f"/modsettings - {t('moderation', lang)}\n"
        f"/warnings - {t('warnings', lang)}\n"
        f"/accessgate - {t('access_gate', lang)}\n"
        f"/subscriptions - {t('subscriptions', lang)}\n"
        f"/lang - {t('language', lang)}"
    )
    await call.message.edit_text(text, reply_markup=_menu_keyboard(lang), disable_web_page_preview=True)
    await call.answer()


@router.callback_query(F.data == "cmd:lang")
async def lang_callback(call: CallbackQuery, state: FSMContext) -> None:
    lang = await resolve_lang(call.message)
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=f"🇬🇧 {t('language_en', lang)}", callback_data="lang:en"),
        InlineKeyboardButton(text=f"🇸🇦 {t('language_ar', lang)}", callback_data="lang:ar"),
    )
    builder.row(InlineKeyboardButton(text=f"⬅ {t('back', lang)}", callback_data="cmd:menu"))
    await call.message.edit_text(t("choose_language", lang), reply_markup=builder.as_markup())
    await call.answer()


@router.callback_query(F.data.startswith("lang:"))
async def lang_choose_callback(call: CallbackQuery) -> None:
    new_lang = call.data.split(":")[1]
    if call.from_user:
        async with SessionLocal() as session:
            await UserService(session).set_language(
                tg_user_id=call.from_user.id,
                language_code=new_lang,
                username=call.from_user.username,
                full_name=call.from_user.full_name,
            )
    await call.message.edit_text(
        t("language_updated", new_lang),
        reply_markup=_menu_keyboard(new_lang),
    )
    await call.answer()


@router.callback_query(F.data == "cmd:cancel")
async def cancel_callback(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.delete()
    await call.answer()


@router.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Cancelled.", reply_markup=None)
