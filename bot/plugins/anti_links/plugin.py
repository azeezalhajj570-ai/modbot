from __future__ import annotations

import re

from aiogram import Dispatcher
from sqlalchemy import select
import structlog

from bot.core.event_bus import Event, EventBus
from bot.config import get_settings
from bot.db.models import Group, ModerationLog
from bot.db.session import SessionLocal
from bot.schemas.settings import PluginManifest
from bot.services.chat_member_service import is_chat_admin
from bot.services.group_service import tg_group_id_candidates
from bot.services.moderation_settings_store import ModerationSettingsStore
from bot.services.moderation_notice_service import build_rule_notice

from .schema import SETTINGS_SCHEMA

LINK_RE = re.compile(r"(https?://|www\.|t\.me/)", re.IGNORECASE)
logger = structlog.get_logger(__name__)


class AntiLinksPlugin:
    manifest = PluginManifest(
        name="anti_links",
        version="1.0.0",
        description="Blocks unauthorized links and applies warning logic.",
        categories=["moderation"],
    )
    settings_schema = SETTINGS_SCHEMA

    def __init__(self) -> None:
        self._event_bus: EventBus | None = None

    async def setup(self, dispatcher: Dispatcher, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        event_bus.subscribe("MessageReceived", self.on_message_received)

    async def teardown(self, dispatcher: Dispatcher, event_bus: EventBus) -> None:
        event_bus.unsubscribe("MessageReceived", self.on_message_received)

    async def on_message_received(self, event: Event) -> None:
        text = event.payload.get("text", "")
        contains_link = bool(event.payload.get("contains_link"))
        logger.info(
            "anti_links_message_received",
            group_tg_id=event.group_id,
            user_id=event.user_id,
            message_id=event.payload.get("message_id"),
            contains_link=contains_link,
            has_text=bool(text),
            text=text,
        )
        if not contains_link and not LINK_RE.search(text):
            logger.info(
                "anti_links_skip_no_link",
                group_tg_id=event.group_id,
                user_id=event.user_id,
                message_id=event.payload.get("message_id"),
                has_text=bool(text),
            )
            return

        message_id = event.payload.get("message_id")
        bot = event.payload.get("bot")
        if not event.group_id or not message_id or not bot:
            logger.info(
                "anti_links_skip_missing_context",
                group_tg_id=event.group_id,
                user_id=event.user_id,
                message_id=message_id,
                has_bot=bool(bot),
                contains_link=contains_link,
            )
            return

        async with SessionLocal() as session:
            group = (
                await session.execute(select(Group).where(Group.tg_group_id.in_(tg_group_id_candidates(int(event.group_id)))))
            ).scalar_one_or_none()
            if not group:
                logger.info(
                    "anti_links_skip_group_not_found",
                    group_tg_id=event.group_id,
                    user_id=event.user_id,
                    message_id=message_id,
                    contains_link=contains_link,
                )
                return

            moderation_settings = await ModerationSettingsStore(session).get_settings(group.id)
            if not moderation_settings.anti_links:
                logger.info(
                    "anti_links_skip_disabled",
                    group_id=group.id,
                    group_tg_id=event.group_id,
                    user_id=event.user_id,
                    message_id=message_id,
                    contains_link=contains_link,
                    anti_links_enabled=False,
                )
                return

            try:
                sender_is_admin = await is_chat_admin(bot, int(event.group_id), event.user_id)
            except Exception as exc:
                logger.warning(
                    "anti_links_admin_check_failed",
                    group_id=group.id,
                    group_tg_id=event.group_id,
                    user_id=event.user_id,
                    message_id=message_id,
                    error=str(exc),
                )
                sender_is_admin = False
            if sender_is_admin:
                logger.info(
                    "anti_links_skip_admin_sender",
                    group_id=group.id,
                    group_tg_id=event.group_id,
                    user_id=event.user_id,
                    message_id=message_id,
                )
                return

            try:
                await bot.delete_message(chat_id=event.group_id, message_id=message_id)
            except Exception as exc:
                logger.warning(
                    "anti_links_delete_failed",
                    group_id=group.id,
                    group_tg_id=event.group_id,
                    user_id=event.user_id,
                    message_id=message_id,
                    contains_link=contains_link,
                    error=str(exc),
                )
                return

            logger.info(
                "anti_links_deleted",
                group_id=group.id,
                group_tg_id=event.group_id,
                user_id=event.user_id,
                message_id=message_id,
                contains_link=contains_link,
            )
            try:
                await bot.send_message(
                    chat_id=event.group_id,
                    text=build_rule_notice(
                        str(event.payload.get("lang") or get_settings().default_language),
                        "anti_links",
                    ),
                )
            except Exception as exc:
                logger.warning(
                    "anti_links_notice_failed",
                    group_id=group.id,
                    group_tg_id=event.group_id,
                    user_id=event.user_id,
                    message_id=message_id,
                    error=str(exc),
                )

            session.add(
                ModerationLog(
                    group_id=group.id,
                    action="delete_link",
                    target_user_id=event.user_id,
                    admin_user_id=None,
                    reason="anti_links",
                    details={"message_id": message_id},
                )
            )
            await session.commit()

        await self._event_bus.publish(
            Event(
                name="LinkDetected",
                group_id=event.group_id,
                user_id=event.user_id,
                payload=event.payload,
            )
        )


plugin = AntiLinksPlugin()
