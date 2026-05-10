from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Conversation, Lead, NotificationEvent, NotificationSettings


DEFAULT_NOTIFICATION_SETTINGS = {
    "notifyOnNewLead": True,
    "notifyOnNeedsHuman": True,
    "dailySummaryEnabled": False,
    "notificationChannel": "none",
    "notificationTarget": None,
    "quietHours": None,
}


@dataclass
class NotificationReadiness:
    has_business_profile: bool
    has_connected_whatsapp: bool
    has_notification_settings: bool
    has_ai_receptionist_enabled: bool
    ready_for_live_test: bool
    missing: list[str]


class NotificationService:
    def __init__(self, session: AsyncSession, *, transport: httpx.AsyncBaseTransport | None = None, timeout_seconds: float = 5.0) -> None:
        self.session = session
        self.transport = transport
        self.timeout_seconds = timeout_seconds

    async def get_or_create_settings(self, tenant_id: int) -> NotificationSettings:
        result = await self.session.execute(select(NotificationSettings).where(NotificationSettings.tenant_id == tenant_id))
        settings = result.scalar_one_or_none()
        if settings is None:
            settings = NotificationSettings(
                tenant_id=tenant_id,
                notify_on_new_lead=True,
                notify_on_needs_human=True,
                daily_summary_enabled=False,
                notification_channel="none",
                notification_target=None,
                quiet_hours=None,
            )
            self.session.add(settings)
            try:
                await self.session.flush()
            except IntegrityError:
                await self.session.rollback()
                result = await self.session.execute(select(NotificationSettings).where(NotificationSettings.tenant_id == tenant_id))
                existing = result.scalar_one_or_none()
                if existing is not None:
                    return existing
                raise
        return settings

    async def update_settings(self, tenant_id: int, payload: dict[str, Any]) -> NotificationSettings:
        settings = await self.get_or_create_settings(tenant_id)
        mapping = {
            "notifyOnNewLead": "notify_on_new_lead",
            "notifyOnNeedsHuman": "notify_on_needs_human",
            "dailySummaryEnabled": "daily_summary_enabled",
            "notificationChannel": "notification_channel",
            "notificationTarget": "notification_target",
            "quietHours": "quiet_hours",
        }
        for external_key, internal_key in mapping.items():
            if external_key in payload:
                setattr(settings, internal_key, payload[external_key])
        settings.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        await self.session.refresh(settings)
        return settings

    async def list_events(self, tenant_id: int, limit: int = 20) -> list[NotificationEvent]:
        return list(
            (
                await self.session.execute(
                    select(NotificationEvent)
                    .where(NotificationEvent.tenant_id == tenant_id)
                    .order_by(NotificationEvent.created_at.desc(), NotificationEvent.id.desc())
                    .limit(limit)
                )
            ).scalars()
        )

    async def create_event(
        self,
        *,
        tenant_id: int,
        type: str,
        title: str,
        body: str,
        channel: str,
        target: str | None,
        related_conversation_id: int | None = None,
        related_lead_id: int | None = None,
        metadata: dict[str, Any] | None = None,
        status: str = "pending",
    ) -> NotificationEvent:
        event = NotificationEvent(
            tenant_id=tenant_id,
            type=type,
            title=title,
            body=body,
            status=status,
            channel=channel,
            target=target,
            related_conversation_id=related_conversation_id,
            related_lead_id=related_lead_id,
            metadata_json=metadata,
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def notify_new_lead(self, tenant_id: int, lead: Lead) -> NotificationEvent:
        settings = await self.get_or_create_settings(tenant_id)
        event = await self.create_event(
            tenant_id=tenant_id,
            type="new_lead",
            title="New lead captured",
            body=self._lead_body(lead),
            channel=settings.notification_channel,
            target=settings.notification_target,
            related_conversation_id=lead.conversation_id,
            related_lead_id=lead.id,
            metadata={"leadStatus": lead.status, "source": lead.source},
        )
        if not settings.notify_on_new_lead:
            event.status = "skipped"
            event.error = "new_lead_notifications_disabled"
            await self.session.flush()
            await self.session.refresh(event)
            return event
        await self.deliver_event(event)
        return event

    async def notify_needs_human(self, tenant_id: int, conversation: Conversation, *, preview_text: str | None = None) -> NotificationEvent:
        settings = await self.get_or_create_settings(tenant_id)
        event = await self.create_event(
            tenant_id=tenant_id,
            type="needs_human",
            title="Conversation needs human reply",
            body=preview_text or conversation.latest_message_text or "A conversation now requires human review.",
            channel=settings.notification_channel,
            target=settings.notification_target,
            related_conversation_id=conversation.id,
            metadata={"conversationStatus": conversation.status},
        )
        if not settings.notify_on_needs_human:
            event.status = "skipped"
            event.error = "needs_human_notifications_disabled"
            await self.session.flush()
            await self.session.refresh(event)
            return event
        await self.deliver_event(event)
        return event

    async def deliver_event(self, event: NotificationEvent) -> NotificationEvent:
        if event.channel == "none":
            event.status = "skipped"
            await self.session.flush()
            await self.session.refresh(event)
            return event

        if event.channel == "webhook":
            payload = self._webhook_payload(event)
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds, transport=self.transport) as client:
                    response = await client.post(str(event.target), json=payload)
                if 200 <= response.status_code < 300:
                    event.status = "sent"
                    event.sent_at = datetime.now(timezone.utc)
                else:
                    event.status = "failed"
                    event.error = f"webhook_http_{response.status_code}"
            except httpx.HTTPError as exc:
                event.status = "failed"
                event.error = str(exc)
            await self.session.flush()
            await self.session.refresh(event)
            return event

        if event.channel == "telegram":
            if not event.target:
                event.status = "failed"
                event.error = "telegram_delivery_missing_chat_id"
                await self.session.flush()
                await self.session.refresh(event)
                return event
            try:
                from bot.config import get_settings
                settings = get_settings()
                bot_token = settings.bot_token
                text = f"*{event.title}*\n\n{event.body}"
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                async with httpx.AsyncClient(timeout=self.timeout_seconds, transport=self.transport) as client:
                    response = await client.post(url, json={
                        "chat_id": int(event.target),
                        "text": text,
                        "parse_mode": "Markdown",
                    })
                if 200 <= response.status_code < 300:
                    event.status = "sent"
                    event.sent_at = datetime.now(timezone.utc)
                else:
                    event.status = "failed"
                    event.error = f"telegram_http_{response.status_code}: {response.text[:200]}"
            except httpx.HTTPError as exc:
                event.status = "failed"
                event.error = str(exc)
            except Exception as exc:
                event.status = "failed"
                event.error = f"telegram_delivery_error: {exc}"
            await self.session.flush()
            await self.session.refresh(event)
            return event

        event.status = "skipped"
        event.error = f"{event.channel}_delivery_not_implemented"
        event.metadata_json = {**(event.metadata_json or {}), "todo": f"{event.channel}_delivery_placeholder"}
        await self.session.flush()
        await self.session.refresh(event)
        return event

    async def send_test_notification(self, tenant_id: int) -> NotificationEvent:
        settings = await self.get_or_create_settings(tenant_id)
        event = await self.create_event(
            tenant_id=tenant_id,
            type="test",
            title="Test notification",
            body="This is a test notification from the operator settings flow.",
            channel=settings.notification_channel,
            target=settings.notification_target,
            metadata={"source": "operator_test"},
        )
        await self.deliver_event(event)
        return event

    async def count_events_by_status(self, tenant_id: int) -> dict[str, int]:
        rows = (
            await self.session.execute(
                select(NotificationEvent.status, func.count(NotificationEvent.id))
                .where(NotificationEvent.tenant_id == tenant_id)
                .group_by(NotificationEvent.status)
            )
        ).all()
        return {str(status): int(count) for status, count in rows}

    def serialize_settings(self, settings: NotificationSettings) -> dict[str, Any]:
        return {
            "notifyOnNewLead": bool(settings.notify_on_new_lead),
            "notifyOnNeedsHuman": bool(settings.notify_on_needs_human),
            "dailySummaryEnabled": bool(settings.daily_summary_enabled),
            "notificationChannel": settings.notification_channel,
            "notificationTarget": settings.notification_target,
            "quietHours": settings.quiet_hours,
        }

    def serialize_event(self, event: NotificationEvent) -> dict[str, Any]:
        return {
            "id": str(event.id),
            "tenantId": str(event.tenant_id),
            "type": event.type,
            "title": event.title,
            "body": event.body,
            "status": event.status,
            "channel": event.channel,
            "target": event.target,
            "relatedConversationId": str(event.related_conversation_id) if event.related_conversation_id else None,
            "relatedLeadId": str(event.related_lead_id) if event.related_lead_id else None,
            "error": event.error,
            "metadata": event.metadata_json,
            "createdAt": event.created_at.isoformat(),
            "sentAt": event.sent_at.isoformat() if event.sent_at else None,
        }

    @staticmethod
    def validate_settings_payload(payload: dict[str, Any]) -> None:
        channel = payload.get("notificationChannel")
        target = payload.get("notificationTarget")
        if channel == "webhook":
            parsed = urlparse(str(target or ""))
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("Webhook notifications require a valid http or https target")
        if channel == "telegram":
            if not target:
                raise ValueError("Telegram notifications require a chat_id target")
            try:
                int(target)
            except (ValueError, TypeError):
                raise ValueError("Telegram notification target must be a numeric chat_id")

    def _lead_body(self, lead: Lead) -> str:
        service = f" for {lead.service}" if lead.service else ""
        name = lead.name or "Unknown contact"
        return f"{name} became a new lead{service}."

    def _webhook_payload(self, event: NotificationEvent) -> dict[str, Any]:
        return {
            "eventId": str(event.id),
            "tenantId": str(event.tenant_id),
            "type": event.type,
            "title": event.title,
            "body": event.body,
            "relatedConversationId": str(event.related_conversation_id) if event.related_conversation_id else None,
            "relatedLeadId": str(event.related_lead_id) if event.related_lead_id else None,
            "createdAt": event.created_at.isoformat(),
            "metadata": event.metadata_json or {},
        }
