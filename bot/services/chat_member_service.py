from __future__ import annotations

from aiogram.types import Message


def is_admin_status(status: object) -> bool:
    return str(status).lower() in {"creator", "administrator", "owner"}


async def is_chat_admin(bot, chat_id: int, user_id: int | None) -> bool:
    if not user_id:
        return False
    member = await bot.get_chat_member(chat_id, user_id)
    return is_admin_status(getattr(member, "status", ""))


async def is_group_admin(message: Message) -> bool:
    if message.chat.type not in {"group", "supergroup"}:
        return True
    if not message.from_user:
        return False

    return await is_chat_admin(message.bot, message.chat.id, message.from_user.id)
