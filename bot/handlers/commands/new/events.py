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
from bot.core.runtime.moderation import ModerationRuntimeService
from bot.utils.i18n import t

from ._shared import group_picker_keyboard, resolve_lang

router = Router(name="cmd_events")


class EventsFlow(StatesGroup):
    selecting_group = State()


async def get_user_groups(message) -> list[dict]:
    uid = message.from_user.id if hasattr(message, "from_user") and message.from_user else 0
    async with SessionLocal() as session:
        return await GroupService(session).list_admin_groups_all(uid)


async def _render_events(message: Message, group_id: int, lang: str, page: int = 0, edit: bool = False) -> None:
    async with SessionLocal() as session:
        events = await ModerationSettingsService(session).list_events(group_id, limit=50)

    pending = [e for e in events if e.get("status") in ("pending", "new")]
    total_pages = max(1, (len(pending) + 4) // 5)
    page = min(page, total_pages - 1)
    chunk = pending[page * 5:(page + 1) * 5]

    if not chunk:
        text = f"✅ {t('events_no_events', lang)}"
    else:
        text = f"⚠️ *{t('events_title', lang)}* — {len(pending)} {t('events_pending_count', lang).format(count=len(pending))}\n\n"
        for ev in chunk:
            cat = ev.get("category", "?")
            username = ev.get("username") or t("events_anonymous", lang)
            preview = (ev.get("text_preview") or "")[:60]
            confidence = int((ev.get("confidence") or 0) * 100)
            text += f"*{username}* — {cat} ({confidence}%)\n`{preview}`\n\n"

    builder = InlineKeyboardBuilder()
    if chunk:
        for ev in chunk:
            eid = ev["id"]
            uid = ev.get("user_id", 0)
            builder.row(
                InlineKeyboardButton(text=f"✅ {t('events_approve', lang)}", callback_data=f"ev:approve:{group_id}:{eid}:{uid}"),
                InlineKeyboardButton(text=f"⚠️ {t('events_warn', lang)}", callback_data=f"ev:warn:{group_id}:{eid}:{uid}"),
                InlineKeyboardButton(text=f"🔇 {t('events_mute', lang)}", callback_data=f"ev:mute:{group_id}:{eid}:{uid}"),
                InlineKeyboardButton(text=f"🚫 {t('events_ban', lang)}", callback_data=f"ev:ban:{group_id}:{eid}:{uid}"),
                InlineKeyboardButton(text=f"❌ {t('events_dismiss', lang)}", callback_data=f"ev:dismiss:{group_id}:{eid}:{uid}"),
            )
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text=f"◀ {t('prev', lang)}", callback_data=f"evp:{group_id}:{page - 1}"))
    if page + 1 < total_pages:
        nav.append(InlineKeyboardButton(text=f"{t('next', lang)} ▶", callback_data=f"evp:{group_id}:{page + 1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text=f"🔄 {t('refresh', lang)}", callback_data=f"evr:{group_id}"))
    builder.row(InlineKeyboardButton(text=f"⬅ {t('back', lang)}", callback_data="cmd:menu"))

    if edit:
        await message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    else:
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.message(Command("events"))
async def events_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    lang = await resolve_lang(message)
    groups = await get_user_groups(message)
    if not groups:
        await message.answer(t("no_groups_found", lang))
        return
    if len(groups) == 1:
        await _render_events(message, groups[0]["id"], lang)
    else:
        await state.set_state(EventsFlow.selecting_group)
        await message.answer(t("select_group", lang), reply_markup=group_picker_keyboard(groups, lang))


@router.callback_query(EventsFlow.selecting_group, F.data.startswith("cg:"))
async def events_group_chosen(call: CallbackQuery, state: FSMContext) -> None:
    group_id = int(call.data.split(":")[1])
    lang = await resolve_lang(call.message)
    await state.clear()
    await _render_events(call.message, group_id, lang, edit=True)
    await call.answer()


@router.callback_query(F.data.startswith("gp:"))
async def events_group_page(call: CallbackQuery) -> None:
    page = int(call.data.split(":")[1])
    lang = await resolve_lang(call.message)
    groups = await get_user_groups(call.message)
    if groups:
        await call.message.edit_text(t("select_group", lang), reply_markup=group_picker_keyboard(groups, lang, page=page))
    await call.answer()


@router.callback_query(F.data.startswith("ev:"))
async def event_action(call: CallbackQuery) -> None:
    parts = call.data.split(":")
    action = parts[1]
    group_id = int(parts[2])
    event_id = int(parts[3])
    user_id = int(parts[4]) if len(parts) > 4 else 0
    lang = await resolve_lang(call.message)

    if action == "dismiss":
        await call.answer(t("events_dismissed", lang))
        await _render_events(call.message, group_id, lang, edit=True)
        return

    if user_id and call.from_user:
        async with SessionLocal() as session:
            await ModerationRuntimeService(session).apply_action(
                group_id=group_id,
                actor_user_id=call.from_user.id,
                user_id=user_id,
                action=action,
                reason=None,
            )
            await session.commit()

    action_labels = {
        "approve": t("events_approved", lang),
        "warn": t("events_warned", lang),
        "mute": t("events_muted", lang),
        "ban": t("events_banned", lang),
    }
    await call.answer(action_labels.get(action, "Done"))
    await _render_events(call.message, group_id, lang, edit=True)


@router.callback_query(F.data.startswith("evp:"))
async def events_page(call: CallbackQuery) -> None:
    _, group_id_str, page_str = call.data.split(":")
    group_id = int(group_id_str)
    page = int(page_str)
    lang = await resolve_lang(call.message)
    await _render_events(call.message, group_id, lang, page=page, edit=True)
    await call.answer()


@router.callback_query(F.data.startswith("evr:"))
async def events_refresh(call: CallbackQuery) -> None:
    group_id = int(call.data.split(":")[1])
    lang = await resolve_lang(call.message)
    await _render_events(call.message, group_id, lang, edit=True)
    await call.answer()
