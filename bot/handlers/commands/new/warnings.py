from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.db.session import SessionLocal
from bot.services.group_service import GroupService
from bot.services.settings_service import SettingsService
from bot.utils.i18n import t

from ._shared import group_picker_keyboard, resolve_lang

router = Router(name="cmd_warnings")


class WarningFlow(StatesGroup):
    selecting_group = State()
    waiting_value = State()


WARN_SETTINGS = {
    "warn_auto_mute": ("bool", "warnings_auto_mute"),
    "warn_mute_limit": ("int", "warnings_mute_limit"),
    "warn_auto_remove": ("bool", "warnings_auto_ban"),
    "warn_remove_limit": ("int", "warnings_ban_limit"),
}


async def get_user_groups(message) -> list[dict]:
    uid = message.from_user.id if hasattr(message, "from_user") and message.from_user else 0
    async with SessionLocal() as session:
        return await GroupService(session).list_admin_groups_all(uid)


async def _render_warnings(message: Message, group_id: int, lang: str, edit: bool = False) -> None:
    async with SessionLocal() as session:
        svc = SettingsService(session)
        settings = {
            k:             await svc.get_one(group_id, k)
            for k in WARN_SETTINGS
        }

    text = (
        f"⚠️ *{t('warnings_title', lang)}*\n\n"
        f"🔇 {t('warnings_auto_mute', lang)}: {'✅' if settings.get('warn_auto_mute') else '❌'}\n"
        f"   {t('warnings_mute_limit', lang)}: {settings.get('warn_mute_limit', 3)}\n"
        f"🚫 {t('warnings_auto_ban', lang)}: {'✅' if settings.get('warn_auto_remove') else '❌'}\n"
        f"   {t('warnings_ban_limit', lang)}: {settings.get('warn_remove_limit', 5)}\n"
    )

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=f"🔇 {t('warnings_auto_mute', lang)}", callback_data=f"wset:toggle:{group_id}:warn_auto_mute"),
        InlineKeyboardButton(text=f"🚫 {t('warnings_auto_ban', lang)}", callback_data=f"wset:toggle:{group_id}:warn_auto_remove"),
    )
    builder.row(
        InlineKeyboardButton(text=f"🔇 {t('warnings_mute_limit', lang)}", callback_data=f"wset:set:{group_id}:warn_mute_limit"),
        InlineKeyboardButton(text=f"🚫 {t('warnings_ban_limit', lang)}", callback_data=f"wset:set:{group_id}:warn_remove_limit"),
    )
    builder.row(InlineKeyboardButton(text=f"⬅ {t('back', lang)}", callback_data="cmd:menu"))

    if edit:
        await message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    else:
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.message(Command("warnings"))
async def warnings_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    lang = await resolve_lang(message)
    groups = await get_user_groups(message)
    if not groups:
        await message.answer(t("no_groups_found", lang))
        return
    if len(groups) == 1:
        await _render_warnings(message, groups[0]["id"], lang)
    else:
        await state.set_state(WarningFlow.selecting_group)
        await message.answer(t("select_group", lang), reply_markup=group_picker_keyboard(groups, lang))


@router.callback_query(WarningFlow.selecting_group, F.data.startswith("cg:"))
async def warnings_group_chosen(call: CallbackQuery, state: FSMContext) -> None:
    group_id = int(call.data.split(":")[1])
    lang = await resolve_lang(call.message)
    await state.clear()
    await _render_warnings(call.message, group_id, lang, edit=True)
    await call.answer()


@router.callback_query(F.data.startswith("gp:"))
async def warnings_group_page(call: CallbackQuery) -> None:
    page = int(call.data.split(":")[1])
    lang = await resolve_lang(call.message)
    groups = await get_user_groups(call.message)
    if groups:
        await call.message.edit_text(t("select_group", lang), reply_markup=group_picker_keyboard(groups, lang, page=page))
    await call.answer()


@router.callback_query(F.data.startswith("wset:"))
async def warnings_setting(call: CallbackQuery, state: FSMContext) -> None:
    parts = call.data.split(":")
    action = parts[1]
    group_id = int(parts[2])
    key = parts[3]
    lang = await resolve_lang(call.message)

    if action == "toggle":
        async with SessionLocal() as session:
            svc = SettingsService(session)
            current = bool(await svc.get_one(group_id, key))
            await svc.set_value(group_id, key, not current)
            await session.commit()
        await call.answer(t("warnings_saved", lang))
        await _render_warnings(call.message, group_id, lang, edit=True)

    elif action == "set":
        await state.set_state(WarningFlow.waiting_value)
        await state.update_data(group_id=group_id, setting_key=key)
        await call.message.edit_text(
            f"{t('warnings_title', lang)}: {t(WARN_SETTINGS[key][1], lang)}\n{t('cancel', lang)}: /cancel",
            reply_markup=InlineKeyboardBuilder().row(
                InlineKeyboardButton(text=f"⬅ {t('back', lang)}", callback_data=f"wset:back:{group_id}")
            ).as_markup()
        )
        await call.answer()


@router.message(WarningFlow.waiting_value)
async def warning_value_input(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    group_id = data["group_id"]
    key = data["setting_key"]
    lang = await resolve_lang(message)
    try:
        value = int(message.text.strip())
        async with SessionLocal() as session:
            svc = SettingsService(session)
            await svc.set_value(group_id, key, value)
            await session.commit()
        await message.answer(t("warnings_saved", lang))
        await _render_warnings(message, group_id, lang)
    except (ValueError, TypeError):
        await message.answer(f"{t('cancel', lang)}: /cancel")
    await state.clear()


@router.callback_query(F.data.startswith("wset:back:"))
async def warning_back(call: CallbackQuery) -> None:
    group_id = int(call.data.split(":")[2])
    lang = await resolve_lang(call.message)
    await _render_warnings(call.message, group_id, lang, edit=True)
    await call.answer()
