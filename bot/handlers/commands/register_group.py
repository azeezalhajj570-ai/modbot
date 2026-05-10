from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.db.session import SessionLocal
from bot.services.group_service import sync_group_admin_roles, upsert_group
from bot.utils.i18n import t

router = Router(name="register_group")


@router.message(Command("registergroup"))
async def register_group(message: Message) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        lang = message.from_user.language_code if message.from_user and message.from_user.language_code else "en"
        await message.answer(t("registergroup_group_only", lang))
        return

    if not message.from_user:
        return

    lang = message.from_user.language_code if message.from_user.language_code else "en"
    member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
    if member.status not in {"creator", "administrator"}:
        await message.answer(t("registergroup_admin_only", lang))
        return

    async with SessionLocal() as session:
        group = await upsert_group(
            session,
            tg_group_id=message.chat.id,
            title=message.chat.title,
            is_active=True,
        )
        if group.registered_by_user_id is None:
            group.registered_by_user_id = message.from_user.id
        await sync_group_admin_roles(session, bot=message.bot, group=group, fallback_actor=message.from_user)
        await session.commit()

    await message.answer(t("registergroup_done", lang))
