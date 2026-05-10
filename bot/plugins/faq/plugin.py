"""FAQ Auto-Answer plugin implementation."""

from __future__ import annotations

from aiogram import Bot, Dispatcher
from sqlalchemy import select
import structlog

from bot.config import get_settings
from bot.core.event_bus import Event, EventBus
from bot.db.models import Group, GroupAdminRole, PluginEnabled
from bot.db.session import SessionLocal
from bot.schemas.settings import PluginManifest
from bot.services.group_service import tg_group_id_candidates
from bot.services.chat_member_service import is_chat_admin
from bot.faq.service import FAQService
from bot.faq.policy import FAQAction
from bot.faq.actions import format_public_reply, format_admin_suggestion

from .schema import SETTINGS_SCHEMA

logger = structlog.get_logger(__name__)

class FAQPlugin:
    manifest = PluginManifest(
        name="faq",
        version="1.0.0",
        description="Automatically answers frequent questions using a deterministic matcher.",
        categories=["automation"],
    )
    settings_schema = SETTINGS_SCHEMA

    async def setup(self, dispatcher: Dispatcher, event_bus: EventBus) -> None:
        event_bus.subscribe("MessageReceived", self.on_message_received)

    async def teardown(self, dispatcher: Dispatcher, event_bus: EventBus) -> None:
        event_bus.unsubscribe("MessageReceived", self.on_message_received)

    async def on_message_received(self, event: Event) -> None:
        if not get_settings().faq_auto_answer_enabled:
            return

        text = str(event.payload.get("text") or "").strip()
        bot = event.payload.get("bot")
        message_id = event.payload.get("message_id")
        user_id = event.user_id
        username = event.payload.get("username", "")
        
        if not text or bot is None or message_id is None or event.group_id is None or user_id is None:
            return

        async with SessionLocal() as session:
            # Resolve group and check if plugin is enabled
            group = (
                await session.execute(
                    select(Group).where(Group.tg_group_id.in_(tg_group_id_candidates(int(event.group_id))))
                )
            ).scalar_one_or_none()
            
            if group is None:
                return
                
            if not await self._is_enabled(session, group.id):
                return
            
            # Check if user is admin
            is_admin = False
            try:
                is_admin = await is_chat_admin(bot, int(event.group_id), user_id)
            except Exception:
                logger.warning("faq_admin_check_failed", group_tg_id=event.group_id, user_id=user_id)

            service = FAQService(session)
            result = await service.process_message(
                group_id=group.id,
                message_id=int(message_id),
                user_id=int(user_id),
                username=username,
                text=text,
                is_admin=is_admin,
                global_enabled=get_settings().faq_auto_answer_enabled
            )
            
            if not result:
                return
                
            if result.action == FAQAction.AUTO_REPLY and result.answer:
                try:
                    await bot.send_message(
                        chat_id=int(event.group_id),
                        text=format_public_reply(result.answer),
                        reply_to_message_id=int(message_id),
                    )
                    await session.commit()
                except Exception as exc:
                    logger.warning(
                        "faq_auto_reply_failed",
                        group_tg_id=event.group_id,
                        message_id=message_id,
                        error=str(exc)
                    )
            elif result.action == FAQAction.SUGGEST_TO_ADMIN:
                await self._notify_admins(session, group, text, result, username, message_id)
                await session.commit()
            elif result.action == FAQAction.LOG_UNANSWERED:
                await session.commit()

    async def _notify_admins(self, session, group, user_question: str, result, username, message_id):
        """Send FAQ suggestion to all group admins via DM."""
        admin_user_ids = (
            await session.execute(
                select(GroupAdminRole.user_id).where(GroupAdminRole.group_id == group.id)
            )
        ).scalars().all()

        if not admin_user_ids:
            logger.info("faq_no_admins_to_notify", group_id=group.id)
            return

        # Fetch the matched entry for the original question text
        matched_question = ""
        if result.faq_entry_id:
            from bot.db.models.faq import FAQEntry
            entry = await session.get(FAQEntry, result.faq_entry_id)
            if entry:
                matched_question = entry.question

        suggestion_text = format_admin_suggestion(
            question=user_question,
            matched_question=matched_question,
            answer=result.answer or "",
            confidence=result.confidence,
        )

        admin_bot = Bot(token=get_settings().bot_token)
        try:
            for admin_uid in admin_user_ids:
                try:
                    await admin_bot.send_message(
                        chat_id=int(admin_uid),
                        text=suggestion_text,
                    )
                except Exception as exc:
                    logger.warning(
                        "faq_admin_notification_failed",
                        group_id=group.id,
                        admin_user_id=admin_uid,
                        error=str(exc),
                    )
        finally:
            await admin_bot.session.close()

    async def _is_enabled(self, session, group_id: int) -> bool:
        enabled = (
            await session.execute(
                select(PluginEnabled.enabled).where(
                    PluginEnabled.group_id == group_id,
                    PluginEnabled.plugin_name == self.manifest.name,
                )
            )
        ).scalar_one_or_none()
        return bool(enabled) if enabled is not None else False

plugin = FAQPlugin()
