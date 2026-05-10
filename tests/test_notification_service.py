from __future__ import annotations

import json

import pytest
from httpx import MockTransport, Request, Response

from bot.db.models import Conversation, Lead
from bot.services.messaging_service import MessagingService
from bot.services.notification_service import NotificationService


@pytest.mark.asyncio
async def test_default_notification_settings_are_created(db_session) -> None:
    context = await MessagingService(db_session).register_user(name="Owner", email="notify@example.com", password="secret123")
    service = NotificationService(db_session)
    settings = await service.get_or_create_settings(context.tenant.id)

    assert settings.notification_channel == "none"
    assert settings.notify_on_new_lead is True
    assert settings.notify_on_needs_human is True


@pytest.mark.asyncio
async def test_webhook_delivery_posts_expected_payload(db_session) -> None:
    captured: list[dict] = []

    def handler(request: Request) -> Response:
        captured.append(json.loads(request.content.decode("utf-8")))
        return Response(200, json={"ok": True})

    context = await MessagingService(db_session).register_user(name="Webhook", email="webhook@example.com", password="secret123")
    service = NotificationService(db_session, transport=MockTransport(handler))
    settings = await service.update_settings(
        context.tenant.id,
        {
            "notificationChannel": "webhook",
            "notificationTarget": "https://hooks.example.com/notify",
        },
    )
    assert settings.notification_channel == "webhook"

    lead = Lead(tenant_id=context.tenant.id, conversation_id=None, name="Mia", phone="+1555", service="Whitening", status="new", source="whatsapp")
    db_session.add(lead)
    await db_session.flush()

    event = await service.notify_new_lead(context.tenant.id, lead)
    assert event.status == "sent"
    assert captured[0]["type"] == "new_lead"
    assert captured[0]["relatedLeadId"] == str(lead.id)


@pytest.mark.asyncio
async def test_none_channel_marks_notification_skipped(db_session) -> None:
    context = await MessagingService(db_session).register_user(name="Skip", email="skip@example.com", password="secret123")
    service = NotificationService(db_session)
    lead = Lead(tenant_id=context.tenant.id, conversation_id=None, name="Mia", phone="+1555", service="Whitening", status="new", source="whatsapp")
    db_session.add(lead)
    await db_session.flush()

    event = await service.notify_new_lead(context.tenant.id, lead)
    assert event.status == "skipped"


@pytest.mark.asyncio
async def test_send_test_notification_creates_event(db_session) -> None:
    context = await MessagingService(db_session).register_user(name="Test", email="test-notify@example.com", password="secret123")
    service = NotificationService(db_session)

    event = await service.send_test_notification(context.tenant.id)
    assert event.type == "test"
    assert event.status == "skipped"


@pytest.mark.asyncio
async def test_needs_human_notification_can_be_created(db_session) -> None:
    context = await MessagingService(db_session).register_user(name="Human", email="human@example.com", password="secret123")
    conversation = Conversation(
        tenant_id=context.tenant.id,
        channel_account_id=1,
        channel="whatsapp",
        contact_id=1,
        status="needs_human",
        latest_message_text="Please call me back",
        unread_count=1,
    )
    db_session.add(conversation)
    await db_session.flush()

    service = NotificationService(db_session)
    event = await service.notify_needs_human(context.tenant.id, conversation, preview_text="Please call me back")
    assert event.type == "needs_human"
    assert event.status == "skipped"
