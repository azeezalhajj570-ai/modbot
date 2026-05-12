from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.db.session import SessionLocal
from bot.services.group_service import GroupService
from bot.services.admin_activity_service import AdminActivityService
from bot.utils.i18n import t

from ._shared import group_picker_keyboard, resolve_lang

router = Router(name="cmd_accessgate")


class AccessGateFlow(StatesGroup):
    selecting_group = State()


async def get_user_groups(message) -> list[dict]:
    uid = message.from_user.id if hasattr(message, "from_user") and message.from_user else 0
    async with SessionLocal() as session:
        return await GroupService(session).list_admin_groups_all(uid)


async def _render_gate(message: Message, group_id: int, lang: str, edit: bool = False) -> None:
    async with SessionLocal() as session:
        from sqlalchemy import select
        from bot.db.models import GroupSetting
        stmt = select(GroupSetting.value).where(
            GroupSetting.group_id == group_id,
            GroupSetting.key == "required_group_tg_ids",
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        required_ids = row if isinstance(row, list) else []

    text = (
        f"🚪 *{t('accessgate_title', lang)}*\n\n"
        f"{t('accessgate_current', lang)}\n"
    )
    if required_ids:
        for gid in required_ids:
            text += f"• `{gid}`\n"
    else:
        text += f"• {t('accessgate_none', lang)}\n"

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=f"⬅ {t('back', lang)}", callback_data="cmd:menu"))
    if edit:
        await message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    else:
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.message(Command("accessgate"))
async def accessgate_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    lang = await resolve_lang(message)
    groups = await get_user_groups(message)
    if not groups:
        await message.answer(t("no_groups_found", lang))
        return
    if len(groups) == 1:
        await _render_gate(message, groups[0]["id"], lang)
    else:
        await state.set_state(AccessGateFlow.selecting_group)
        await message.answer(t("select_group", lang), reply_markup=group_picker_keyboard(groups, lang))


@router.callback_query(AccessGateFlow.selecting_group, F.data.startswith("cg:"))
async def gate_group_chosen(call: CallbackQuery, state: FSMContext) -> None:
    group_id = int(call.data.split(":")[1])
    lang = await resolve_lang(call.message)
    await state.clear()
    await _render_gate(call.message, group_id, lang, edit=True)
    await call.answer()


@router.callback_query(F.data.startswith("gp:"))
async def gate_group_page(call: CallbackQuery) -> None:
    page = int(call.data.split(":")[1])
    lang = await resolve_lang(call.message)
    groups = await get_user_groups(call.message)
    if groups:
        await call.message.edit_text(t("select_group", lang), reply_markup=group_picker_keyboard(groups, lang, page=page))
    await call.answer()
