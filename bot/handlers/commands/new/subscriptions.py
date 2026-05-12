from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import get_settings
from bot.db.session import SessionLocal
from bot.services.subscription_service import SubscriptionService
from bot.utils.i18n import t

from ._shared import resolve_lang

router = Router(name="cmd_subscriptions")

PLANS = ["free", "pro", "business"]


@router.message(Command("subscriptions"))
async def subscriptions_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    lang = await resolve_lang(message)
    settings = get_settings()
    is_owner = message.from_user and message.from_user.id in set(settings.bot_owner_ids)
    if not is_owner:
        await message.answer(t("permission_denied", lang))
        return

    async with SessionLocal() as session:
        subs = await SubscriptionService(session).list_active_subscriptions()

    if not subs:
        text = f"📭 {t('subscriptions_no_subs', lang)}"
    else:
        text = f"💳 *{t('subscriptions_title', lang)}*\n\n"
        for s in subs[:20]:
            name = s.get("full_name") or s.get("username") or str(s.get("tg_user_id", "?"))
            plan = s.get("plan", "free")
            status = s.get("status", "active")
            text += f"• {name} — `{plan}` ({status})\n"

    await message.answer(text, parse_mode="Markdown")


@router.callback_query(F.data == "cmd:subscriptions")
async def subscriptions_callback(call: CallbackQuery) -> None:
    lang = await resolve_lang(call.message)
    settings = get_settings()
    is_owner = call.from_user and call.from_user.id in set(settings.bot_owner_ids)
    if not is_owner:
        await call.answer(t("permission_denied", lang), show_alert=True)
        return

    async with SessionLocal() as session:
        subs = await SubscriptionService(session).list_active_subscriptions()

    if not subs:
        text = f"📭 {t('subscriptions_no_subs', lang)}"
    else:
        text = f"💳 *{t('subscriptions_title', lang)}*\n\n"
        for s in subs[:20]:
            name = s.get("full_name") or s.get("username") or str(s.get("tg_user_id", "?"))
            plan = s.get("plan", "free")
            status = s.get("status", "active")
            text += f"• {name} — `{plan}` ({status})\n"

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=f"⬅ {t('back', lang)}", callback_data="cmd:menu"))
    await call.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    await call.answer()
