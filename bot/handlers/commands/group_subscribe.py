from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from sqlalchemy import select

from bot.db.session import SessionLocal
from bot.db.models import Group, SubscriptionPlan, GroupSubscriber, GroupSubscriberStatus, GroupPaymentMode
from bot.services.group_subscription_service import GroupSubscriptionService
from bot.services.group_payment_service import GroupPaymentService
from bot.utils.i18n import t

router = Router(name="group_subscription")
logger = logging.getLogger(__name__)


@router.message(Command("subscribe"))
async def show_plans(message: Message) -> None:
    if message.chat.type != "private":
        await message.answer("Please use this command in private chat.")
        return

    # For MVP, we might need a way to link to a specific group.
    # If no group_id provided, we could list groups where the bot is admin and has paid access enabled.
    async with SessionLocal() as session:
        # Placeholder: finding groups where the bot can sell access
        # This is a bit complex for a simple command without params.
        # Let's assume /subscribe <tg_group_id> or just show instructions.
        await message.answer("To subscribe to a group, please use the group's unique subscription link or contact the admin.")

@router.message(Command("my_subscription"))
async def my_subscription(message: Message) -> None:
    if not message.from_user:
        return
    
    async with SessionLocal() as session:
        stmt = select(GroupSubscriber).where(
            GroupSubscriber.user_id == message.from_user.id,
            GroupSubscriber.status == GroupSubscriberStatus.ACTIVE
        )
        subs = (await session.execute(stmt)).scalars().all()
        
        if not subs:
            await message.answer("You don't have any active subscriptions.")
            return
        
        text = "Your active subscriptions:\n\n"
        for sub in subs:
            # Get group title
            group_stmt = select(Group).where(Group.id == sub.group_id)
            group = (await session.execute(group_stmt)).scalar_one()
            text += f"- {group.title}: expires at {sub.expires_at.strftime('%Y-%m-%d')}\n"
        
        await message.answer(text)
