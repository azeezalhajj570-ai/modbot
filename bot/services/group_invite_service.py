from __future__ import annotations

import logging
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

logger = logging.getLogger(__name__)


class GroupInviteService:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def create_single_use_invite_link(
        self,
        chat_id: int,
        expire_seconds: int = 86400,
        member_limit: int = 1,
        name: str | None = None,
        creates_join_request: bool = False,
    ) -> str | None:
        """
        Creates a single-use invite link for a group.
        Requires 'can_invite_users' permission.

        When creates_join_request is True, member_limit is omitted
        (Telegram API restriction — approval links cannot have a member limit).
        """
        expire_date = datetime.utcnow() + timedelta(seconds=expire_seconds)

        try:
            kwargs: dict = {
                "chat_id": chat_id,
                "expire_date": expire_date,
                "name": name,
            }
            if creates_join_request:
                kwargs["creates_join_request"] = True
            else:
                kwargs["member_limit"] = member_limit

            link = await self.bot.create_chat_invite_link(**kwargs)
            return link.invite_link
        except TelegramBadRequest as exc:
            logger.error("failed_to_create_invite_link", extra={
                "chat_id": chat_id,
                "error": str(exc)
            })
            return None
        except Exception as exc:
            logger.exception("unexpected_error_creating_invite_link", extra={
                "chat_id": chat_id,
                "error": str(exc)
            })
            return None

    async def revoke_invite_link(self, chat_id: int, invite_link: str) -> bool:
        try:
            await self.bot.revoke_chat_invite_link(chat_id=chat_id, invite_link=invite_link)
            return True
        except Exception as exc:
            logger.error("failed_to_revoke_invite_link", extra={
                "chat_id": chat_id,
                "error": str(exc)
            })
            return False
