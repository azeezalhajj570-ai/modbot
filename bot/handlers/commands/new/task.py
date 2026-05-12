from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from uuid import uuid4

from bot.db.session import SessionLocal
from bot.services.group_service import GroupService
from bot.services.task_service import TaskService
from bot.utils.i18n import t

from ._shared import group_picker_keyboard, resolve_lang, cancel_keyboard

router = Router(name="cmd_task")

TASK_TYPES = ["reply_message", "notify_destination", "welcome_flow", "lead_capture", "escalation_alert"]
DELIVERY_MODES = ["text", "forward", "copy", "text_and_forward", "text_and_copy"]


class TaskFlow(StatesGroup):
    selecting_group = State()
    choosing_type = State()
    entering_keyword = State()
    entering_template = State()
    entering_destination = State()
    choosing_delivery = State()


async def get_user_groups(message) -> list[dict]:
    uid = message.from_user.id if hasattr(message, "from_user") and message.from_user else 0
    async with SessionLocal() as session:
        return await GroupService(session).list_admin_groups_all(uid)


async def _render_tasks(message: Message, group_id: int, lang: str, edit: bool = False) -> None:
    async with SessionLocal() as session:
        tasks = await TaskService(session, dispatch_agent_job=None).list_assignments(
            actor_user_id=message.from_user.id if hasattr(message, "from_user") and message.from_user else 0,
            group_id=group_id,
        )

    if not tasks:
        text = f"📭 {t('task_no_tasks', lang)}"
    else:
        text = f"✅ *{t('task_title', lang)}*\n\n"
        for tk in tasks[:10]:
            kw = tk.get("task_key", "?")
            status = "✅" if tk.get("enabled") else "⏸"
            tt = tk.get("executor_type", "?")
            text += f"{status} `{kw}` ({tt})\n"

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=f"➕ {t('task_new', lang)}", callback_data=f"tk:new:{group_id}"))
    builder.row(InlineKeyboardButton(text=f"⬅ {t('back', lang)}", callback_data="cmd:menu"))

    if edit:
        await message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    else:
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.message(Command("task"))
async def task_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    lang = await resolve_lang(message)
    groups = await get_user_groups(message)
    if not groups:
        await message.answer(t("no_groups_found", lang))
        return
    if len(groups) == 1:
        await _render_tasks(message, groups[0]["id"], lang)
    else:
        await state.set_state(TaskFlow.selecting_group)
        await message.answer(t("select_group", lang), reply_markup=group_picker_keyboard(groups, lang))


@router.callback_query(TaskFlow.selecting_group, F.data.startswith("cg:"))
async def task_group_chosen(call: CallbackQuery, state: FSMContext) -> None:
    group_id = int(call.data.split(":")[1])
    lang = await resolve_lang(call.message)
    await state.clear()
    await _render_tasks(call.message, group_id, lang, edit=True)
    await call.answer()


@router.callback_query(F.data.startswith("gp:"))
async def task_group_page(call: CallbackQuery) -> None:
    page = int(call.data.split(":")[1])
    lang = await resolve_lang(call.message)
    groups = await get_user_groups(call.message)
    if groups:
        await call.message.edit_text(t("select_group", lang), reply_markup=group_picker_keyboard(groups, lang, page=page))
    await call.answer()


@router.callback_query(F.data.startswith("tk:new:"))
async def task_new(call: CallbackQuery, state: FSMContext) -> None:
    group_id = int(call.data.split(":")[2])
    lang = await resolve_lang(call.message)
    await state.set_state(TaskFlow.choosing_type)
    await state.update_data(group_id=group_id)
    builder = InlineKeyboardBuilder()
    for tt in TASK_TYPES:
        label_key = f"task_{tt}"
        builder.row(InlineKeyboardButton(text=t(label_key, lang), callback_data=f"tk:type:{tt}"))
    builder.row(InlineKeyboardButton(text=f"⬅ {t('back', lang)}", callback_data=f"tk:back:{group_id}"))
    await call.message.edit_text(f"📋 {t('task_type', lang)}:", reply_markup=builder.as_markup())
    await call.answer()


@router.callback_query(F.data.startswith("tk:type:"))
async def task_type_chosen(call: CallbackQuery, state: FSMContext) -> None:
    task_type = call.data.split(":")[2]
    data = await state.get_data()
    data["executor_type"] = task_type
    await state.update_data(data)
    lang = await resolve_lang(call.message)
    await state.set_state(TaskFlow.entering_keyword)
    await call.message.edit_text(t("task_keyword_prompt_new", lang), reply_markup=cancel_keyboard(lang))
    await call.answer()


@router.message(TaskFlow.entering_keyword)
async def task_keyword_received(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    data["task_key"] = message.text.strip()
    await state.update_data(data)
    lang = await resolve_lang(message)
    await state.set_state(TaskFlow.entering_template)
    await message.answer(t("task_template_prompt_new", lang), reply_markup=cancel_keyboard(lang))


@router.message(TaskFlow.entering_template)
async def task_template_received(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    data["template"] = message.text.strip()
    await state.update_data(data)
    lang = await resolve_lang(message)
    tt = data.get("executor_type", "reply_message")

    if tt == "notify_destination":
        await state.set_state(TaskFlow.entering_destination)
        await message.answer(t("task_destination_prompt", lang), reply_markup=cancel_keyboard(lang))
    else:
        await _save_task(message, state)


@router.message(TaskFlow.entering_destination)
async def task_destination_received(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    data["destination"] = message.text.strip()
    await state.update_data(data)
    lang = await resolve_lang(message)
    await state.set_state(TaskFlow.choosing_delivery)
    builder = InlineKeyboardBuilder()
    for dm in DELIVERY_MODES:
        builder.row(InlineKeyboardButton(text=t(f"task_notify_mode_{dm}", lang), callback_data=f"tk:delivery:{dm}"))
    builder.row(InlineKeyboardButton(text=f"⬅ {t('back', lang)}", callback_data="tk:cancel"))
    await message.answer(t("task_delivery_mode_prompt", lang), reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("tk:delivery:"))
async def task_delivery_chosen(call: CallbackQuery, state: FSMContext) -> None:
    delivery = call.data.split(":")[2]
    data = await state.get_data()
    data["delivery_mode"] = delivery
    await state.update_data(data)
    await call.answer()
    await _save_task(call.message, state)


async def _save_task(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    group_id = data["group_id"]
    lang = await resolve_lang(message)
    try:
        async with SessionLocal() as session:
            svc = TaskService(session, dispatch_agent_job=None)
            task_key = data.get("task_key", "")
            executor_type = data.get("executor_type", "reply_message")
            config = {"message_template": data.get("template", "")}
            if data.get("destination"):
                config["destination"] = data["destination"]
            if data.get("delivery_mode"):
                config["delivery_mode"] = data["delivery_mode"]
            await svc.save_assignment(
                actor_user_id=message.from_user.id if hasattr(message, "from_user") and message.from_user else 0,
                group_id=group_id,
                task_key=task_key,
                executor_type=executor_type,
                enabled=True,
                conditions={"text_contains": task_key},
                config=config,
            )
            await session.commit()
        await message.answer(f"✅ {t('task_created', lang)}")
        await _render_tasks(message, group_id, lang)
    except Exception as e:
        await message.answer(f"❌ {e}")
    await state.clear()


@router.callback_query(F.data == "tk:cancel")
async def task_create_cancel(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    group_id = data.get("group_id", 0)
    lang = await resolve_lang(call.message)
    await state.clear()
    await _render_tasks(call.message, group_id, lang, edit=True)
    await call.answer()
