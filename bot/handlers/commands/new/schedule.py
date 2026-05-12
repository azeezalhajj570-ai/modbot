from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.db.session import SessionLocal
from bot.services.group_service import GroupService
from bot.services.scheduled_message_service import ScheduledMessageService
from bot.utils.i18n import t

from ._shared import group_picker_keyboard, resolve_lang, cancel_keyboard

router = Router(name="cmd_schedule")


class ScheduleFlow(StatesGroup):
    selecting_group = State()
    waiting_text = State()
    waiting_schedule = State()


async def get_user_groups(message) -> list[dict]:
    uid = message.from_user.id if hasattr(message, "from_user") and message.from_user else 0
    async with SessionLocal() as session:
        return await GroupService(session).list_admin_groups_all(uid)


async def _render_schedule(message: Message, group_id: int, lang: str, page: int = 0, edit: bool = False) -> None:
    async with SessionLocal() as session:
        entries = await ScheduledMessageService(session).list_entries(group_id=group_id)

    total_pages = max(1, (len(entries) + 4) // 5)
    page = min(page, total_pages - 1)
    chunk = entries[page * 5:(page + 1) * 5]

    if not chunk:
        text = f"📭 {t('schedule_no_msgs', lang)}"
    else:
        text = f"📢 *{t('schedule_title', lang)}*\n\n"
        for e in chunk:
            preview = (e.get("text") or "")[:50]
            sched = e.get("send_at") or e.get("cron") or "?"
            status = e.get("status", "pending")
            icon = "✅" if status == "sent" else "⏳"
            text += f"{icon} `{preview}` — {sched}\n"

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=f"➕ {t('schedule_new', lang)}", callback_data=f"sc:new:{group_id}"))
    if chunk:
        for e in chunk[:5]:
            eid = e.get("id", "")
            preview = (e.get("text") or "")[:30]
            builder.row(
                InlineKeyboardButton(text=f"✏️ {preview}", callback_data=f"sc:show:{group_id}:{eid}"),
            )
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text=f"◀ {t('prev', lang)}", callback_data=f"scp:{group_id}:{page - 1}"))
    if page + 1 < total_pages:
        nav.append(InlineKeyboardButton(text=f"{t('next', lang)} ▶", callback_data=f"scp:{group_id}:{page + 1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text=f"⬅ {t('back', lang)}", callback_data="cmd:menu"))

    if edit:
        await message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    else:
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.message(Command("schedule"))
async def schedule_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    lang = await resolve_lang(message)
    groups = await get_user_groups(message)
    if not groups:
        await message.answer(t("no_groups_found", lang))
        return
    if len(groups) == 1:
        await _render_schedule(message, groups[0]["id"], lang)
    else:
        await state.set_state(ScheduleFlow.selecting_group)
        await message.answer(t("select_group", lang), reply_markup=group_picker_keyboard(groups, lang))


@router.callback_query(ScheduleFlow.selecting_group, F.data.startswith("cg:"))
async def schedule_group_chosen(call: CallbackQuery, state: FSMContext) -> None:
    group_id = int(call.data.split(":")[1])
    lang = await resolve_lang(call.message)
    await state.clear()
    await _render_schedule(call.message, group_id, lang, edit=True)
    await call.answer()


@router.callback_query(F.data.startswith("gp:"))
async def schedule_group_page(call: CallbackQuery) -> None:
    page = int(call.data.split(":")[1])
    lang = await resolve_lang(call.message)
    groups = await get_user_groups(call.message)
    if groups:
        await call.message.edit_text(t("select_group", lang), reply_markup=group_picker_keyboard(groups, lang, page=page))
    await call.answer()


@router.callback_query(F.data.startswith("scp:"))
async def schedule_page(call: CallbackQuery) -> None:
    _, group_id_str, page_str = call.data.split(":")
    group_id = int(group_id_str)
    page = int(page_str)
    lang = await resolve_lang(call.message)
    await _render_schedule(call.message, group_id, lang, page=page, edit=True)
    await call.answer()


@router.callback_query(F.data.startswith("sc:new:"))
async def schedule_new(call: CallbackQuery, state: FSMContext) -> None:
    group_id = int(call.data.split(":")[2])
    lang = await resolve_lang(call.message)
    await state.set_state(ScheduleFlow.waiting_text)
    await state.update_data(group_id=group_id)
    await call.message.edit_text(t("schedule_text_prompt", lang), reply_markup=cancel_keyboard(lang))
    await call.answer()


@router.message(ScheduleFlow.waiting_text)
async def schedule_text_received(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    data["text"] = message.text.strip()
    await state.update_data(data)
    lang = await resolve_lang(message)
    await state.set_state(ScheduleFlow.waiting_schedule)
    builder = InlineKeyboardBuilder()
    presets = [
        ("daily_9", "0 9 * * *"),
        ("daily_12", "0 12 * * *"),
        ("daily_18", "0 18 * * *"),
        ("weekdays", "0 9 * * 1-5"),
        ("weekly_mon", "0 9 * * 1"),
        ("monthly_1st", "0 9 1 * *"),
    ]
    for label_key, _ in presets:
        from bot.utils.i18n import t as _t
        builder.row(InlineKeyboardButton(text=_t(f"sched_form_{label_key}", lang), callback_data=f"sc:preset:{label_key}"))
    builder.row(InlineKeyboardButton(text=f"⬅ {t('back', lang)}", callback_data="sc:back"))
    await message.answer(t("schedule_presets", lang), reply_markup=builder.as_markup())
    await state.update_data(presets=presets)


@router.callback_query(F.data.startswith("sc:preset:"))
async def schedule_preset_chosen(call: CallbackQuery, state: FSMContext) -> None:
    label_key = call.data.split(":")[2]
    data = await state.get_data()
    presets = data.get("presets", [])
    cron = None
    for lk, c in presets:
        if lk == label_key:
            cron = c
            break
    if cron:
        data["schedule"] = cron
    else:
        data["schedule"] = "0 9 * * *"
    await state.update_data(data)
    await _create_scheduled(call.message, state)
    await call.answer()


async def _create_scheduled(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    group_id = data["group_id"]
    text = data.get("text", "")
    schedule = data.get("schedule", "0 9 * * *")
    lang = await resolve_lang(message)
    try:
        async with SessionLocal() as session:
            await ScheduledMessageService(session).save_entry(
                group_id=group_id,
                text=text,
                schedule=schedule,
            )
            await session.commit()
        await message.answer(f"✅ {t('schedule_created', lang)}")
        await _render_schedule(message, group_id, lang)
    except Exception as e:
        await message.answer(f"❌ {e}")
    await state.clear()
