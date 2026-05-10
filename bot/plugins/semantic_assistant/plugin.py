from __future__ import annotations

from urllib.parse import urlsplit

from aiogram import Dispatcher
from sqlalchemy import select
import structlog

from bot.config import get_settings
from bot.core.event_bus import Event, EventBus
from bot.db.models import Group, PluginEnabled
from bot.db.session import SessionLocal
from bot.schemas.settings import PluginManifest
from bot.services.group_service import tg_group_id_candidates
from bot.services.semantic_search_service import SemanticSearchService
from bot.services.settings_service import SettingsService

from .schema import SETTINGS_SCHEMA

logger = structlog.get_logger(__name__)


class SemanticAssistantPlugin:
    manifest = PluginManifest(
        name="semantic_assistant",
        version="1.0.0",
        description="Replies to group messages using the semantic search service.",
        categories=["automation"],
    )
    settings_schema = SETTINGS_SCHEMA

    async def setup(self, dispatcher: Dispatcher, event_bus: EventBus) -> None:
        event_bus.subscribe("MessageReceived", self.on_message_received)

    async def teardown(self, dispatcher: Dispatcher, event_bus: EventBus) -> None:
        event_bus.unsubscribe("MessageReceived", self.on_message_received)

    async def on_message_received(self, event: Event) -> None:
        text = str(event.payload.get("text") or "").strip()
        bot = event.payload.get("bot")
        message_id = event.payload.get("message_id")
        if not text or bot is None or message_id is None or event.group_id is None:
            return

        settings = get_settings()
        service_url = str(settings.semantic_search_url or "").strip()
        if not service_url:
            return

        parsed = urlsplit(service_url)
        if not parsed.scheme or not parsed.netloc:
            logger.warning("semantic_assistant_invalid_service_url", service_url=service_url)
            return

        async with SessionLocal() as session:
            group = (
                await session.execute(select(Group).where(Group.tg_group_id.in_(tg_group_id_candidates(int(event.group_id)))))
            ).scalar_one_or_none()
            if group is None:
                return
            if not await self._is_enabled(session, group.id):
                return

            settings_service = SettingsService(session)
            service_name = str(await settings_service.get_one(group.id, "semantic_assistant_service_name") or "").strip()
            resource_scope = str(await settings_service.get_one(group.id, "semantic_assistant_resource_scope") or "").strip()
            reply_prefix = str(await settings_service.get_one(group.id, "semantic_assistant_reply_prefix") or "").strip()
            top_k = await settings_service.get_one(group.id, "semantic_assistant_top_k")

        service = SemanticSearchService(
            f"{parsed.scheme}://{parsed.netloc}",
            timeout=settings.semantic_search_timeout,
            search_path=parsed.path or settings.semantic_search_path,
        )
        result = await service.search(
            text,
            service_name=service_name or None,
            resource_scope=resource_scope or None,
            top_k=max(1, int(top_k or 3)),
        )
        if result is None:
            return

        reply_text = result.text
        if result.url and result.url not in reply_text:
            reply_text = f"{reply_text}\n{result.url}"
        if reply_prefix:
            reply_text = f"{reply_prefix}\n{reply_text}"

        try:
            await bot.send_message(
                chat_id=int(event.group_id),
                text=reply_text,
                reply_to_message_id=int(message_id),
            )
        except Exception as exc:
            logger.warning(
                "semantic_assistant_reply_failed",
                group_tg_id=event.group_id,
                user_id=event.user_id,
                message_id=message_id,
                error=str(exc),
            )

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


plugin = SemanticAssistantPlugin()
