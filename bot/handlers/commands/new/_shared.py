from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.db.session import SessionLocal
from bot.services.group_service import GroupService
from bot.services.user_service import UserService
from bot.utils.i18n import t


async def resolve_lang(message: Message) -> str:
    from bot.config import get_settings
    fallback = get_settings().default_language
    if not message.from_user:
        return fallback
    async with SessionLocal() as session:
        return await UserService(session).resolve_language(message.from_user.id, fallback=fallback)


async def get_user_groups(message: Message) -> list[dict]:
    if not message.from_user:
        return []
    async with SessionLocal() as session:
        return await GroupService(session).list_admin_groups_all(message.from_user.id)


def group_picker_keyboard(groups: list[dict], lang: str, page: int = 0, page_size: int = 8) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    start = page * page_size
    chunk = groups[start:start + page_size]
    for g in chunk:
        title = g.get("title", f"Group {g['id']}")
        builder.row(InlineKeyboardButton(text=title, callback_data=f"cg:{g['id']}"))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text=f"◀ {t('prev', lang)}", callback_data=f"gp:{page - 1}"))
    if start + page_size < len(groups):
        nav.append(InlineKeyboardButton(text=f"{t('next', lang)} ▶", callback_data=f"gp:{page + 1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text=f"❌ {t('cancel', lang)}", callback_data="cmd:cancel"))
    return builder.as_markup()


def back_button(lang: str, action: str = "cmd:menu") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=f"⬅ {t('back', lang)}", callback_data=action))
    return builder.as_markup()


def cancel_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=f"❌ {t('cancel', lang)}", callback_data="cmd:cancel"))
    return builder.as_markup()
