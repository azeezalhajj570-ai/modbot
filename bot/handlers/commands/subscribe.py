from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardRemove

from bot.config import get_settings
from bot.db.session import SessionLocal
from bot.services.menu_button_service import configure_private_chat_menu_button
from bot.services.subscription_service import SubscriptionService, build_owner_notification
from bot.utils.i18n import t

router = Router(name="subscription")
logger = logging.getLogger(__name__)


def _normalize_message(text: str | None, limit: int = 1000) -> str | None:
    if not text:
        return None
    normalized = text.strip()
    if not normalized:
        return None
    if len(normalized) > limit:
        normalized = normalized[:limit].rstrip()
    return normalized or None

@router.message(Command("subscribe"))
async def request_subscription(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    await state.clear()

    parts = (message.text or "").split(maxsplit=1)
    note = _normalize_message(parts[1] if len(parts) > 1 else "")
    actor = message.from_user
    language = actor.language_code or "en"

    async with SessionLocal() as session:
        request = await SubscriptionService(session).create_request(
            tg_user_id=actor.id,
            username=getattr(actor, "username", None),
            full_name=getattr(actor, "full_name", None),
            language_code=getattr(actor, "language_code", None),
            message=note,
        )

    await configure_private_chat_menu_button(bot=message.bot, user_id=actor.id, enabled=False)
    await message.answer(
        t("subscription_request_acknowledged", language),
        reply_markup=ReplyKeyboardRemove(),
    )

    settings = get_settings()
    review_link = settings.webapp_url or settings.dashboard_url
    actor_label = actor.username or actor.full_name or str(actor.id)
    notification = build_owner_notification(
        request_id=request.id,
        actor_label=actor_label,
        actor_id=actor.id,
        message_text=note,
        review_url=review_link,
    )

    for owner_id in settings.bot_owner_ids:
        try:
            await message.bot.send_message(owner_id, notification, disable_web_page_preview=True)
        except Exception as exc:  # pragma: no cover
            logger.warning("failed to notify owner about subscription request", extra={"owner_id": owner_id, "error": str(exc)})
