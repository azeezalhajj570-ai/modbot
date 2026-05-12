from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, desc

from bot.core.runtime.moderation import ModerationRuntimeService
from bot.db.models.moderation import ModerationLog
from bot.db.session import SessionLocal
from bot.services.group_service import GroupService
from bot.utils.i18n import t

from ._shared import group_picker_keyboard, resolve_lang

router = Router(name="cmd_restricted")


class RestrictedFlow(StatesGroup):
    selecting_group = State()


async def get_user_groups(message) -> list[dict]:
    uid = message.from_user.id if hasattr(message, "from_user") and message.from_user else 0
    async with SessionLocal() as session:
        return await GroupService(session).list_admin_groups_all(uid)


async def _render_restricted(message: Message, group_id: int, lang: str, edit: bool = False) -> None:
    mute_actions = {"mute_user", "mute_warn_limit", "mute_ad_user", "mute_spam_user", "mute_unauthorized_command_user"}
    ban_actions = {"ban_user", "remove_warn_limit", "ban_unauthorized_command_user"}

    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(
                    ModerationLog.target_user_id,
                    ModerationLog.action,
                    ModerationLog.reason,
                    ModerationLog.created_at,
                )
                .where(ModerationLog.group_id == group_id, ModerationLog.action.in_(mute_actions | ban_actions))
                .order_by(desc(ModerationLog.created_at))
                .distinct(ModerationLog.target_user_id)
            )
        ).all()

    muted = [r for r in rows if r.action in mute_actions]
    banned = [r for r in rows if r.action in ban_actions]

    if not muted and not banned:
        text = f"✅ {t('restricted_none', lang)}"
    else:
        text = f"🔇 *{t('restricted_title', lang)}*\n\n"
        if muted:
            text += f"🔊 *{t('restricted_muted', lang)}:*\n"
            for r in muted[:10]:
                text += f"• `{r.target_user_id}` — {r.reason or '—'}\n"
        if banned:
            text += f"\n🚫 *{t('restricted_banned', lang)}:*\n"
            for r in banned[:10]:
                text += f"• `{r.target_user_id}` — {r.reason or '—'}\n"

    builder = InlineKeyboardBuilder()
    if muted:
        for r in muted[:5]:
            builder.row(
                InlineKeyboardButton(text=f"🔊 {t('restricted_unmute', lang)} {r.target_user_id}", callback_data=f"rst:unmute:{group_id}:{r.target_user_id}")
            )
    if banned:
        for r in banned[:5]:
            builder.row(
                InlineKeyboardButton(text=f"🚫 {t('restricted_unban', lang)} {r.target_user_id}", callback_data=f"rst:unban:{group_id}:{r.target_user_id}")
            )
    builder.row(InlineKeyboardButton(text=f"🔄 {t('refresh', lang)}", callback_data=f"rstr:{group_id}"))
    builder.row(InlineKeyboardButton(text=f"⬅ {t('back', lang)}", callback_data="cmd:menu"))

    if edit:
        await message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    else:
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.message(Command("restricted"))
async def restricted_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    lang = await resolve_lang(message)
    groups = await get_user_groups(message)
    if not groups:
        await message.answer(t("no_groups_found", lang))
        return
    if len(groups) == 1:
        await _render_restricted(message, groups[0]["id"], lang)
    else:
        await state.set_state(RestrictedFlow.selecting_group)
        await message.answer(t("select_group", lang), reply_markup=group_picker_keyboard(groups, lang))


@router.callback_query(RestrictedFlow.selecting_group, F.data.startswith("cg:"))
async def restricted_group_chosen(call: CallbackQuery, state: FSMContext) -> None:
    group_id = int(call.data.split(":")[1])
    lang = await resolve_lang(call.message)
    await state.clear()
    await _render_restricted(call.message, group_id, lang, edit=True)
    await call.answer()


@router.callback_query(F.data.startswith("gp:"))
async def restricted_group_page(call: CallbackQuery) -> None:
    page = int(call.data.split(":")[1])
    lang = await resolve_lang(call.message)
    groups = await get_user_groups(call.message)
    if groups:
        await call.message.edit_text(t("select_group", lang), reply_markup=group_picker_keyboard(groups, lang, page=page))
    await call.answer()


@router.callback_query(F.data.startswith("rst:"))
async def restricted_action(call: CallbackQuery) -> None:
    _, action, group_id_str, user_id_str = call.data.split(":")
    group_id = int(group_id_str)
    user_id = int(user_id_str)
    lang = await resolve_lang(call.message)

    if call.from_user:
        async with SessionLocal() as session:
            await ModerationRuntimeService(session).apply_action(
                group_id=group_id,
                actor_user_id=call.from_user.id,
                user_id=user_id,
                action=action,
                reason=None,
            )
            await session.commit()

    labels = {"unmute": t("restricted_unmute", lang), "unban": t("restricted_unban", lang)}
    await call.answer(labels.get(action, "Done"))
    await _render_restricted(call.message, group_id, lang, edit=True)


@router.callback_query(F.data.startswith("rstr:"))
async def restricted_refresh(call: CallbackQuery) -> None:
    group_id = int(call.data.split(":")[1])
    lang = await resolve_lang(call.message)
    await _render_restricted(call.message, group_id, lang, edit=True)
    await call.answer()
