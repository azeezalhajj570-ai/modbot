from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import ChannelAccount, Contact, Conversation, Lead, Message
from bot.db.session import get_session
from bot.services.messaging_service import (
    MessagingAuthContext,
    MessagingAuthError,
    MessagingIntegrationError,
    MessagingService,
    MessagingWebhookAuthError,
)
from bot.services.notification_service import NotificationService
from ._shared import EmailPasswordLoginRequest, RegisterRequest

router = APIRouter(prefix="/api", tags=["messaging"])


@router.post("/auth/register")
async def register(
    payload: RegisterRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    service = MessagingService(session)
    try:
        context = await service.register_user(
            name=payload.name,
            email=payload.email,
            password=payload.password,
        )
        return {"access_token": context.access_token}
    except MessagingAuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/auth/login")
async def login(
    payload: EmailPasswordLoginRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    service = MessagingService(session)
    try:
        context = await service.login_user(
            identifier=payload.email,
            password=payload.password,
        )
        return {"access_token": context.access_token}
    except MessagingAuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


class BusinessProfilePatchRequest(BaseModel):
    businessName: str = ""
    category: str = ""
    services: list[dict[str, Any]] = Field(default_factory=list)
    openingHours: str = ""
    location: str = ""
    bookingLink: str | None = None
    escalationContact: str | None = None
    faqs: list[dict[str, str]] = Field(default_factory=list)
    forbiddenClaims: list[str] = Field(default_factory=list)


class SendMessageRequest(BaseModel):
    text: str = Field(min_length=1)


class DraftMessagePatchRequest(BaseModel):
    text: str = Field(min_length=1)


class LeadPatchRequest(BaseModel):
    name: str | None = None
    phone: str | None = None
    service: str | None = None
    preferred_time: str | None = Field(default=None, alias="preferredTime")
    status: str | None = None


class AutomationPatchRequest(BaseModel):
    enabled: bool | None = None
    config: dict[str, Any] | None = None


class DevSimulateMessageRequest(BaseModel):
    text: str = "Hi, I want to book an appointment and know the price."
    contactName: str = "Demo Customer"
    phone: str = "+15550001111"


class NotificationSettingsPatchRequest(BaseModel):
    notifyOnNewLead: bool | None = None
    notifyOnNeedsHuman: bool | None = None
    dailySummaryEnabled: bool | None = None
    notificationChannel: str | None = Field(default=None, pattern="^(none|webhook|telegram|email)$")
    notificationTarget: str | None = None
    quietHours: dict[str, Any] | None = None


async def get_messaging_context(
    session: AsyncSession = Depends(get_session),
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
) -> MessagingAuthContext:
    service = MessagingService(session)

    if authorization:
        token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else authorization.strip()
        try:
            return await service.authenticate_bearer_token(token)
        except MessagingAuthError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    if x_telegram_init_data is not None:
        try:
            return await service.authenticate_telegram(x_telegram_init_data)
        except (MessagingAuthError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authentication")


def _serialize_channel(channel: ChannelAccount) -> dict[str, Any]:
    return {
        "id": str(channel.id),
        "type": channel.type,
        "displayName": channel.display_name,
        "status": channel.status,
        "qrCode": channel.qr_code,
        "lastSyncedAt": channel.last_synced_at.isoformat() if channel.last_synced_at else None,
    }


def _serialize_conversation(conversation: Conversation, contact: Contact | None = None) -> dict[str, Any]:
    return {
        "id": str(conversation.id),
        "channelAccountId": str(conversation.channel_account_id),
        "channel": conversation.channel,
        "contactName": contact.name if contact else None,
        "contactPhone": contact.phone if contact else None,
        "latestMessage": conversation.latest_message_text,
        "status": conversation.status,
        "unreadCount": conversation.unread_count,
        "updatedAt": conversation.updated_at.isoformat(),
    }


def _serialize_message(message: Message) -> dict[str, Any]:
    raw_payload = message.raw_payload or {}
    delivery = raw_payload.get("delivery") if isinstance(raw_payload.get("delivery"), dict) else None
    safe_payload: dict[str, Any] = {}
    for key in ("source", "reason", "confidence", "safetyCategory", "autoSendRequested", "edited", "editedAt", "discarded", "discardedAt"):
        if key in raw_payload:
            safe_payload[key] = raw_payload[key]
    if delivery:
        safe_payload["delivery"] = {
            key: delivery[key]
            for key in ("provider", "status", "messageId", "error", "source", "instance")
            if key in delivery
        }
    return {
        "id": str(message.id),
        "conversationId": str(message.conversation_id),
        "direction": message.direction,
        "senderType": message.sender_type,
        "status": message.status,
        "text": message.text,
        "createdAt": message.created_at.isoformat(),
        "rawPayload": safe_payload or None,
    }


def _serialize_lead(lead: Lead) -> dict[str, Any]:
    return {
        "id": str(lead.id),
        "conversationId": str(lead.conversation_id) if lead.conversation_id else None,
        "name": lead.name,
        "phone": lead.phone,
        "service": lead.service,
        "preferredTime": lead.preferred_time,
        "status": lead.status,
        "source": lead.source,
        "createdAt": lead.created_at.isoformat(),
    }


def _notification_service(session: AsyncSession) -> NotificationService:
    return NotificationService(session)


@router.get("/me")
async def get_me(context: MessagingAuthContext = Depends(get_messaging_context), session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    return await MessagingService(session).get_me(context.user)


@router.get("/tenants/current")
async def get_current_tenant(
    context: MessagingAuthContext = Depends(get_messaging_context),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await MessagingService(session).get_tenant_payload(context.tenant)


@router.get("/notification-settings")
async def get_notification_settings(
    context: MessagingAuthContext = Depends(get_messaging_context),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    service = _notification_service(session)
    settings = await service.get_or_create_settings(context.tenant.id)
    await session.commit()
    return {"settings": service.serialize_settings(settings)}


@router.patch("/notification-settings")
async def patch_notification_settings(
    body: NotificationSettingsPatchRequest,
    context: MessagingAuthContext = Depends(get_messaging_context),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    payload = body.model_dump(exclude_none=True)
    service = _notification_service(session)
    try:
        service.validate_settings_payload(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    settings = await service.update_settings(context.tenant.id, payload)
    await session.commit()
    return {"settings": service.serialize_settings(settings)}


@router.get("/notifications")
async def get_notifications(
    limit: int = 20,
    context: MessagingAuthContext = Depends(get_messaging_context),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    service = _notification_service(session)
    events = await service.list_events(context.tenant.id, limit=limit)
    return {"notifications": [service.serialize_event(event) for event in events]}


@router.post("/notifications/test")
async def post_test_notification(
    context: MessagingAuthContext = Depends(get_messaging_context),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    service = _notification_service(session)
    notification = await service.send_test_notification(context.tenant.id)
    await session.commit()
    return {"notification": service.serialize_event(notification)}


@router.patch("/tenants/current/business-profile")
async def patch_business_profile(
    body: BusinessProfilePatchRequest,
    context: MessagingAuthContext = Depends(get_messaging_context),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    tenant = await MessagingService(session).update_business_profile(context.tenant, body.model_dump())
    return await MessagingService(session).get_tenant_payload(tenant)


@router.get("/channels")
async def get_channels(
    context: MessagingAuthContext = Depends(get_messaging_context),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    channels = await MessagingService(session).list_channels(context.tenant.id)
    return {"channels": [_serialize_channel(channel) for channel in channels]}


@router.post("/channels/whatsapp/connect")
async def connect_whatsapp(
    context: MessagingAuthContext = Depends(get_messaging_context),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        channel = await MessagingService(session).connect_whatsapp(context.tenant.id)
    except MessagingIntegrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"channel": _serialize_channel(channel), "qrCode": channel.qr_code}


@router.post("/channels/whatsapp/disconnect")
async def disconnect_whatsapp(
    context: MessagingAuthContext = Depends(get_messaging_context),
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    try:
        await MessagingService(session).disconnect_whatsapp(context.tenant.id)
    except MessagingIntegrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True}


@router.get("/channels/{channel_id}/status")
async def get_channel_status(
    channel_id: int,
    context: MessagingAuthContext = Depends(get_messaging_context),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        channel = await MessagingService(session).get_channel_status(context.tenant.id, channel_id)
    except MessagingAuthError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MessagingIntegrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _serialize_channel(channel)


@router.post("/channels/{channel_id}/refresh-qr")
async def refresh_channel_qr(
    channel_id: int,
    context: MessagingAuthContext = Depends(get_messaging_context),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        channel = await MessagingService(session).refresh_channel_qr(context.tenant.id, channel_id)
    except MessagingAuthError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MessagingIntegrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"qrCode": channel.qr_code}


@router.get("/conversations")
async def get_conversations(
    context: MessagingAuthContext = Depends(get_messaging_context),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    service = MessagingService(session)
    conversations = await service.list_conversations(context.tenant.id)
    contacts = {
        contact.id: contact
        for contact in (
            await session.execute(
                select(Contact).where(Contact.tenant_id == context.tenant.id)
            )
        ).scalars()
    }
    return {"conversations": [_serialize_conversation(conversation, contacts.get(conversation.contact_id)) for conversation in conversations]}


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: int,
    context: MessagingAuthContext = Depends(get_messaging_context),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    service = MessagingService(session)
    try:
        conversation, messages = await service.get_conversation(context.tenant.id, conversation_id)
    except MessagingAuthError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    result = await session.execute(select(Contact).where(Contact.id == conversation.contact_id))
    contact = result.scalar_one_or_none()
    return {
        "conversation": _serialize_conversation(conversation, contact),
        "messages": [_serialize_message(message) for message in messages],
    }


@router.post("/conversations/{conversation_id}/send-message")
async def post_conversation_message(
    conversation_id: int,
    body: SendMessageRequest,
    context: MessagingAuthContext = Depends(get_messaging_context),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        message = await MessagingService(session).send_message(context.tenant.id, conversation_id, body.text)
    except MessagingAuthError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MessagingIntegrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _serialize_message(message)


@router.post("/conversations/{conversation_id}/handoff")
async def post_conversation_handoff(
    conversation_id: int,
    context: MessagingAuthContext = Depends(get_messaging_context),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        conversation = await MessagingService(session).handoff_conversation(context.tenant.id, conversation_id)
    except MessagingAuthError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    result = await session.execute(select(Contact).where(Contact.id == conversation.contact_id))
    contact = result.scalar_one_or_none()
    return _serialize_conversation(conversation, contact)


@router.patch("/messages/{message_id}")
async def patch_message_draft(
    message_id: int,
    body: DraftMessagePatchRequest,
    context: MessagingAuthContext = Depends(get_messaging_context),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        message = await MessagingService(session).update_draft_message(context.tenant.id, message_id, text=body.text)
    except MessagingAuthError as exc:
        detail = str(exc)
        status_code = 404 if detail == "Message not found" else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return _serialize_message(message)


@router.post("/messages/{message_id}/send-draft")
async def post_send_draft_message(
    message_id: int,
    context: MessagingAuthContext = Depends(get_messaging_context),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        message = await MessagingService(session).send_draft_message(context.tenant.id, message_id)
    except MessagingAuthError as exc:
        detail = str(exc)
        status_code = 404 if detail == "Message not found" else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return _serialize_message(message)


@router.delete("/messages/{message_id}")
async def delete_draft_message(
    message_id: int,
    context: MessagingAuthContext = Depends(get_messaging_context),
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    try:
        await MessagingService(session).discard_draft_message(context.tenant.id, message_id)
    except MessagingAuthError as exc:
        detail = str(exc)
        status_code = 404 if detail == "Message not found" else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return {"ok": True}


@router.get("/leads")
async def get_leads(
    context: MessagingAuthContext = Depends(get_messaging_context),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    leads = await MessagingService(session).list_leads(context.tenant.id)
    return {"leads": [_serialize_lead(lead) for lead in leads]}


@router.get("/leads/{lead_id}")
async def get_lead(
    lead_id: int,
    context: MessagingAuthContext = Depends(get_messaging_context),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        lead = await MessagingService(session).get_lead(context.tenant.id, lead_id)
    except MessagingAuthError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _serialize_lead(lead)


@router.patch("/leads/{lead_id}")
async def patch_lead(
    lead_id: int,
    body: LeadPatchRequest,
    context: MessagingAuthContext = Depends(get_messaging_context),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        lead = await MessagingService(session).update_lead(
            context.tenant.id,
            lead_id,
            body.model_dump(exclude_none=True, by_alias=False),
        )
    except MessagingAuthError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _serialize_lead(lead)


@router.get("/automations")
async def get_automations(
    context: MessagingAuthContext = Depends(get_messaging_context),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    automations = await MessagingService(session).list_automations(context.tenant.id)
    return {
        "automations": [
            {
                "id": str(automation.id),
                "name": automation.name,
                "slug": automation.slug,
                "description": automation.description,
                "channel": automation.channel,
                "enabled": bool(automation.enabled),
            }
            for automation in automations
        ]
    }


@router.patch("/automations/{automation_id}")
async def patch_automation(
    automation_id: int,
    body: AutomationPatchRequest,
    context: MessagingAuthContext = Depends(get_messaging_context),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        automation = await MessagingService(session).update_automation(
            context.tenant.id,
            automation_id,
            body.model_dump(exclude_none=True),
        )
    except MessagingAuthError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "id": str(automation.id),
        "name": automation.name,
        "slug": automation.slug,
        "description": automation.description,
        "channel": automation.channel,
        "enabled": bool(automation.enabled),
    }


@router.get("/skills")
async def get_skills(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    skills = await MessagingService(session).list_skills()
    return {
        "skills": [
            {
                "id": str(skill.id),
                "name": skill.name,
                "slug": skill.slug,
                "description": skill.description,
                "channel": skill.channel,
            }
            for skill in skills
        ]
    }


@router.post("/skills/{skill_identifier}/run")
async def run_skill(
    skill_identifier: str,
    context: MessagingAuthContext = Depends(get_messaging_context),
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    try:
        await MessagingService(session).run_skill(context.tenant.id, skill_identifier)
    except MessagingAuthError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@router.get("/analytics/overview")
async def get_analytics(
    context: MessagingAuthContext = Depends(get_messaging_context),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await MessagingService(session).get_analytics_overview(context.tenant.id)


@router.post("/webhooks/evolution/{channel_account_id}")
async def post_evolution_webhook(
    channel_account_id: int,
    payload: dict[str, Any],
    x_evolution_webhook_secret: str | None = Header(default=None, alias="X-Evolution-Webhook-Secret"),
    secret: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        return await MessagingService(session).ingest_evolution_webhook_for_channel(
            channel_account_id,
            payload,
            webhook_secret=x_evolution_webhook_secret or secret,
        )
    except MessagingAuthError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MessagingWebhookAuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except MessagingIntegrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/dev/simulate-whatsapp-message")
async def post_dev_simulated_message(
    body: DevSimulateMessageRequest,
    context: MessagingAuthContext = Depends(get_messaging_context),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await MessagingService(session).simulate_whatsapp_message(
        context.tenant.id,
        text=body.text,
        contact_name=body.contactName,
        phone=body.phone,
    )
