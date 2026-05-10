from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl

from sqlalchemy import Select, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import get_settings
from bot.dashboard.api.auth import (
    create_dashboard_jwt,
    decode_dashboard_jwt,
    verify_telegram_init_data_identity,
)
from bot.db.models import (
    Automation,
    ChannelAccount,
    Contact,
    Conversation,
    Lead,
    Message,
    Skill,
    SkillRun,
    Tenant,
    User,
)
from bot.services.telegram_webapp_auth import (
    TelegramWebAppAuthError,
    TelegramWebAppIdentity,
)
from bot.services.evolution_service import (
    EvolutionApiError,
    EvolutionWebhookAuthError,
    EvolutionWhatsAppService,
)
from bot.services.ai_receptionist_service import AIReceptionistService
from bot.services.notification_service import NotificationService


BOOKING_INTENT_WORDS = ("book", "appointment", "schedule", "price", "cost", "interested")
HUMAN_HANDOFF_WORDS = ("human", "agent", "person", "call me")
DEFAULT_BUSINESS_PROFILE = {
    "businessName": "",
    "category": "",
    "services": [],
    "openingHours": "",
    "location": "",
    "bookingLink": "",
    "escalationContact": "",
    "faqs": [],
    "forbiddenClaims": [],
}
DEFAULT_AUTOMATIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "AI Receptionist",
        "slug": "ai-receptionist",
        "description": "Greets inbound customers and keeps AI-led conversations active.",
        "channel": "whatsapp",
        "enabled": True,
    },
    {
        "name": "Lead Capture",
        "slug": "lead-capture",
        "description": "Creates leads from booking-intent messages.",
        "channel": "whatsapp",
        "enabled": True,
    },
    {
        "name": "Human Handoff",
        "slug": "human-handoff",
        "description": "Escalates conversations that need a human operator.",
        "channel": "whatsapp",
        "enabled": True,
    },
    {
        "name": "CRM Sync",
        "slug": "crm-sync",
        "description": "Reserved for future CRM synchronization.",
        "channel": "all",
        "enabled": False,
    },
    {
        "name": "Daily Summary",
        "slug": "daily-summary",
        "description": "Reserved for daily reporting across conversations and leads.",
        "channel": "all",
        "enabled": False,
    },
)
DEFAULT_SKILLS: tuple[dict[str, Any], ...] = (
    {
        "name": "Capture Lead",
        "slug": "capture-lead",
        "description": "Creates or updates a lead from inbound WhatsApp messages.",
        "channel": "whatsapp",
        "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}},
    },
    {
        "name": "Human Handoff",
        "slug": "human-handoff",
        "description": "Marks a conversation as requiring a human response.",
        "channel": "whatsapp",
        "input_schema": {"type": "object", "properties": {"conversationId": {"type": "string"}}},
    },
    {
        "name": "Daily Summary",
        "slug": "daily-summary",
        "description": "Summarizes the day for the workspace.",
        "channel": "all",
        "input_schema": {"type": "object", "properties": {}},
    },
)


@dataclass
class MessagingAuthContext:
    user: User
    tenant: Tenant
    access_token: str


class MessagingAuthError(ValueError):
    pass


class MessagingIntegrationError(RuntimeError):
    pass


class MessagingWebhookAuthError(ValueError):
    pass


class MessagingService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        evolution_service: EvolutionWhatsAppService | None = None,
        ai_receptionist_service: AIReceptionistService | None = None,
        notification_service: NotificationService | None = None,
    ) -> None:
        self.session = session
        self.settings = get_settings()
        self.evolution = evolution_service or EvolutionWhatsAppService.from_env()
        self.ai_receptionist = ai_receptionist_service or AIReceptionistService(self.settings)
        self.notifications = notification_service or NotificationService(self.session)

    async def authenticate_bearer_token(self, token: str) -> MessagingAuthContext:
        try:
            identity = decode_dashboard_jwt(token)
        except ValueError as exc:
            raise MessagingAuthError(str(exc)) from exc

        result = await self.session.execute(select(User).where(User.id == identity.user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise MessagingAuthError("Unknown session user")
        tenant = await self._ensure_tenant_for_user(user)
        return MessagingAuthContext(user=user, tenant=tenant, access_token=token)

    async def authenticate_telegram(self, init_data: str | None, app_boundary: str | None = None) -> MessagingAuthContext:
        identity = self._resolve_telegram_identity(init_data, app_boundary=app_boundary)
        user = await self._get_user_by_telegram_id(identity.user_id)
        if user is None:
            user = User(
                tg_user_id=identity.user_id,
                username=identity.username,
                full_name=self._full_name(identity.first_name, identity.last_name),
                language_code="en",
            )
            self.session.add(user)
            await self.session.flush()
        else:
            user.username = identity.username or user.username
            full_name = self._full_name(identity.first_name, identity.last_name)
            if full_name:
                user.full_name = full_name
        tenant = await self._ensure_tenant_for_user(user)
        token = self._create_token_for_user(user)
        await self.session.commit()
        return MessagingAuthContext(user=user, tenant=tenant, access_token=token)

    async def register_user(self, *, name: str, email: str, password: str) -> MessagingAuthContext:
        existing = await self._get_user_by_email(email)
        if existing is not None:
            raise MessagingAuthError("Email is already registered")
        user = User(
            email=email.strip().lower(),
            full_name=name.strip() or email.strip().lower(),
            password_hash=self._hash_password(password),
            language_code="en",
        )
        self.session.add(user)
        await self.session.flush()
        tenant = await self._ensure_tenant_for_user(user)
        token = self._create_token_for_user(user)
        await self.session.commit()
        return MessagingAuthContext(user=user, tenant=tenant, access_token=token)

    async def login_user(self, *, identifier: str, password: str) -> MessagingAuthContext:
        normalized = identifier.strip().lower()
        user = await self._get_user_by_email(normalized)
        if user is None:
            result = await self.session.execute(select(User).where(func.lower(func.coalesce(User.username, "")) == normalized))
            user = result.scalar_one_or_none()
        if user is None or not user.password_hash or not hmac.compare_digest(user.password_hash, self._hash_password(password)):
            raise MessagingAuthError("Invalid credentials")
        tenant = await self._ensure_tenant_for_user(user)
        token = self._create_token_for_user(user)
        await self.session.commit()
        return MessagingAuthContext(user=user, tenant=tenant, access_token=token)

    async def logout(self) -> dict[str, bool]:
        return {"ok": True}

    async def get_me(self, user: User) -> dict[str, Any]:
        return {
            "id": str(user.id),
            "email": user.email,
            "name": user.full_name or user.username or user.email or f"User {user.id}",
            "telegramUsername": user.username,
        }

    async def get_tenant_payload(self, tenant: Tenant) -> dict[str, Any]:
        settings = await self.notifications.get_or_create_settings(tenant.id)
        await self.session.commit()
        return {
            "id": str(tenant.id),
            "name": tenant.name,
            "businessProfile": tenant.business_profile or DEFAULT_BUSINESS_PROFILE,
            "notificationSettings": self.notifications.serialize_settings(settings),
        }

    async def update_business_profile(self, tenant: Tenant, payload: dict[str, Any]) -> Tenant:
        tenant.business_profile = payload
        tenant.updated_at = datetime.utcnow()
        await self.session.commit()
        await self.session.refresh(tenant)
        return tenant

    async def list_channels(self, tenant_id: int) -> list[ChannelAccount]:
        return list(
            (
                await self.session.execute(
                    select(ChannelAccount).where(ChannelAccount.tenant_id == tenant_id).order_by(ChannelAccount.id)
                )
            ).scalars()
        )

    async def ensure_whatsapp_channel(self, tenant_id: int) -> ChannelAccount:
        result = await self.session.execute(
            select(ChannelAccount)
            .where(ChannelAccount.tenant_id == tenant_id, ChannelAccount.type == "whatsapp")
            .order_by(ChannelAccount.id)
        )
        channel = result.scalar_one_or_none()
        if channel is None:
            channel = ChannelAccount(
                tenant_id=tenant_id,
                type="whatsapp",
                display_name="WhatsApp Primary",
                status="pending",
                qr_code=self._mock_qr_svg("Connect WhatsApp"),
                credentials_encrypted=None,
                last_synced_at=datetime.utcnow(),
            )
            self.session.add(channel)
            await self.session.flush()
        return channel

    async def connect_whatsapp(self, tenant_id: int) -> ChannelAccount:
        channel = await self.ensure_whatsapp_channel(tenant_id)
        if self.evolution.enabled:
            try:
                if channel.external_account_id:
                    state = await self.evolution.refresh_qr_code(channel)
                else:
                    state = await self.evolution.create_instance(
                        tenant_id=tenant_id,
                        channel_account_id=channel.id,
                        display_name=channel.display_name,
                    )
            except EvolutionApiError as exc:
                channel.status = "error"
                channel.last_synced_at = datetime.utcnow()
                await self.session.commit()
                raise MessagingIntegrationError(str(exc)) from exc
            channel.external_account_id = state.external_account_id
            channel.status = state.status
            channel.qr_code = state.qr_code
            channel.credentials_encrypted = state.metadata
        else:
            channel.status = "pending"
            channel.qr_code = self._mock_qr_svg(channel.display_name)
        channel.last_synced_at = datetime.utcnow()
        await self.session.commit()
        await self.session.refresh(channel)
        return channel

    async def disconnect_whatsapp(self, tenant_id: int) -> None:
        channel = await self.ensure_whatsapp_channel(tenant_id)
        if self.evolution.enabled and channel.external_account_id:
            try:
                state = await self.evolution.disconnect_instance(channel)
            except EvolutionApiError as exc:
                raise MessagingIntegrationError(str(exc)) from exc
            channel.status = state.status
            channel.qr_code = state.qr_code
            channel.external_account_id = None
            channel.credentials_encrypted = None
        else:
            channel.status = "disconnected"
            channel.qr_code = None
        channel.last_synced_at = datetime.utcnow()
        await self.session.commit()

    async def get_channel(self, tenant_id: int, channel_id: int) -> ChannelAccount:
        result = await self.session.execute(select(ChannelAccount).where(ChannelAccount.id == channel_id))
        channel = result.scalar_one_or_none()
        if channel is None or channel.tenant_id != tenant_id:
            raise MessagingAuthError("Channel not found")
        return channel

    async def refresh_channel_qr(self, tenant_id: int, channel_id: int) -> ChannelAccount:
        channel = await self.get_channel(tenant_id, channel_id)
        if self.evolution.enabled and channel.type == "whatsapp" and channel.external_account_id:
            try:
                state = await self.evolution.refresh_qr_code(channel)
            except EvolutionApiError as exc:
                channel.status = "error"
                channel.last_synced_at = datetime.utcnow()
                await self.session.commit()
                raise MessagingIntegrationError(str(exc)) from exc
            channel.status = state.status
            channel.qr_code = state.qr_code
            channel.credentials_encrypted = state.metadata
        else:
            channel.status = "pending"
            channel.qr_code = self._mock_qr_svg(channel.display_name)
        channel.last_synced_at = datetime.utcnow()
        await self.session.commit()
        await self.session.refresh(channel)
        return channel

    async def get_channel_status(self, tenant_id: int, channel_id: int) -> ChannelAccount:
        channel = await self.get_channel(tenant_id, channel_id)
        if not (self.evolution.enabled and channel.type == "whatsapp" and channel.external_account_id):
            return channel
        try:
            state = await self.evolution.get_instance_status(channel)
        except EvolutionApiError as exc:
            channel.status = "error"
            channel.last_synced_at = datetime.utcnow()
            await self.session.commit()
            raise MessagingIntegrationError(str(exc)) from exc
        channel.status = state.status
        channel.qr_code = state.qr_code
        channel.credentials_encrypted = state.metadata
        channel.last_synced_at = datetime.utcnow()
        await self.session.commit()
        await self.session.refresh(channel)
        return channel

    async def list_conversations(self, tenant_id: int) -> list[Conversation]:
        return list(
            (
                await self.session.execute(
                    select(Conversation)
                    .where(Conversation.tenant_id == tenant_id)
                    .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
                )
            ).scalars()
        )

    async def get_conversation(self, tenant_id: int, conversation_id: int) -> tuple[Conversation, list[Message]]:
        result = await self.session.execute(select(Conversation).where(Conversation.id == conversation_id))
        conversation = result.scalar_one_or_none()
        if conversation is None or conversation.tenant_id != tenant_id:
            raise MessagingAuthError("Conversation not found")
        messages = list(
            (
                await self.session.execute(
                    select(Message)
                    .where(Message.conversation_id == conversation_id, Message.tenant_id == tenant_id)
                    .order_by(Message.created_at.asc(), Message.id.asc())
                )
            ).scalars()
        )
        return conversation, messages

    async def get_message(self, tenant_id: int, message_id: int) -> Message:
        result = await self.session.execute(select(Message).where(Message.id == message_id))
        message = result.scalar_one_or_none()
        if message is None or message.tenant_id != tenant_id:
            raise MessagingAuthError("Message not found")
        return message

    async def update_draft_message(self, tenant_id: int, message_id: int, *, text: str) -> Message:
        message = await self.get_message(tenant_id, message_id)
        self._ensure_draft_editable(message)
        message.text = text
        if message.raw_payload:
            message.raw_payload = {
                **message.raw_payload,
                "edited": True,
                "editedAt": datetime.utcnow().isoformat(),
            }
        await self.session.commit()
        await self.session.refresh(message)
        return message

    async def send_draft_message(self, tenant_id: int, message_id: int) -> Message:
        message = await self.get_message(tenant_id, message_id)
        self._ensure_draft_sendable(message)

        conversation = await self._require_conversation(tenant_id, message.conversation_id)
        contact = await self._require_contact(conversation.contact_id)
        channel = await self.get_channel(tenant_id, message.channel_account_id)

        delivery = await self._deliver_outbound_message(
            channel=channel,
            contact=contact,
            text=message.text,
            source=(message.raw_payload or {}).get("source", "ai_receptionist"),
        )
        message.status = delivery["status"]
        message.external_message_id = delivery.get("messageId")
        message.raw_payload = {
            **(message.raw_payload or {}),
            "delivery": delivery,
        }
        if message.status == "sent":
            self._touch_conversation(conversation, text=message.text, inbound=False)
        else:
            conversation.status = "needs_human"

        await self.session.commit()
        await self.session.refresh(message)
        return message

    async def discard_draft_message(self, tenant_id: int, message_id: int) -> None:
        message = await self.get_message(tenant_id, message_id)
        self._ensure_draft_editable(message)
        message.status = "discarded"
        if message.raw_payload:
            message.raw_payload = {
                **message.raw_payload,
                "discarded": True,
                "discardedAt": datetime.utcnow().isoformat(),
            }
        await self.session.commit()

    async def send_message(self, tenant_id: int, conversation_id: int, text: str) -> Message:
        conversation = await self._require_conversation(tenant_id, conversation_id)
        contact = await self._require_contact(conversation.contact_id)
        message = Message(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            channel_account_id=conversation.channel_account_id,
            direction="outbound",
            sender_type="human",
            status="sent",
            text=text,
            raw_payload={"source": "miniapp"},
        )
        self.session.add(message)
        self._touch_conversation(conversation, text=text, inbound=False)
        channel = await self.get_channel(tenant_id, conversation.channel_account_id)
        delivery = await self._deliver_outbound_message(channel=channel, contact=contact, text=text, source="miniapp")
        message.status = delivery["status"]
        message.external_message_id = delivery.get("messageId")
        message.raw_payload = {"source": "miniapp", "delivery": delivery}
        if message.status == "failed":
            conversation.status = "needs_human"
        await self.session.commit()
        await self.session.refresh(message)
        return message

    async def handoff_conversation(self, tenant_id: int, conversation_id: int) -> Conversation:
        conversation = await self._require_conversation(tenant_id, conversation_id)
        await self._mark_conversation_needs_human(conversation, preview_text=conversation.latest_message_text)
        await self.session.commit()
        await self.session.refresh(conversation)
        return conversation

    async def list_leads(self, tenant_id: int) -> list[Lead]:
        return list(
            (
                await self.session.execute(
                    select(Lead).where(Lead.tenant_id == tenant_id).order_by(Lead.updated_at.desc(), Lead.id.desc())
                )
            ).scalars()
        )

    async def get_lead(self, tenant_id: int, lead_id: int) -> Lead:
        result = await self.session.execute(select(Lead).where(Lead.id == lead_id))
        lead = result.scalar_one_or_none()
        if lead is None or lead.tenant_id != tenant_id:
            raise MessagingAuthError("Lead not found")
        return lead

    async def update_lead(self, tenant_id: int, lead_id: int, patch: dict[str, Any]) -> Lead:
        lead = await self.get_lead(tenant_id, lead_id)
        for key in ("name", "phone", "service", "preferred_time", "status"):
            if key in patch:
                setattr(lead, key, patch[key])
        lead.updated_at = datetime.utcnow()
        await self.session.commit()
        await self.session.refresh(lead)
        return lead

    async def list_automations(self, tenant_id: int) -> list[Automation]:
        await self._ensure_default_skills()
        tenant = await self._require_tenant(tenant_id)
        await self._ensure_default_automations(tenant)
        await self.session.commit()
        return list(
            (
                await self.session.execute(
                    select(Automation).where(Automation.tenant_id == tenant_id).order_by(Automation.id)
                )
            ).scalars()
        )

    async def update_automation(self, tenant_id: int, automation_id: int, patch: dict[str, Any]) -> Automation:
        result = await self.session.execute(select(Automation).where(Automation.id == automation_id))
        automation = result.scalar_one_or_none()
        if automation is None or automation.tenant_id != tenant_id:
            raise MessagingAuthError("Automation not found")
        if "enabled" in patch:
            automation.enabled = bool(patch["enabled"])
        if "config" in patch:
            automation.config = patch["config"]
        automation.updated_at = datetime.utcnow()
        await self.session.commit()
        await self.session.refresh(automation)
        return automation

    async def list_skills(self) -> list[Skill]:
        await self._ensure_default_skills()
        await self.session.commit()
        return list((await self.session.execute(select(Skill).order_by(Skill.id))).scalars())

    async def run_skill(self, tenant_id: int, skill_identifier: str, conversation_id: int | None = None) -> SkillRun:
        skill = await self._resolve_skill(skill_identifier)
        skill_run = SkillRun(
            tenant_id=tenant_id,
            skill_id=skill.id,
            conversation_id=conversation_id,
            input={"source": "manual", "skillIdentifier": skill_identifier},
            output={"ok": True, "skill": skill.slug},
            status="success",
        )
        self.session.add(skill_run)
        await self.session.commit()
        await self.session.refresh(skill_run)
        return skill_run

    async def get_analytics_overview(self, tenant_id: int) -> dict[str, int]:
        today = datetime.now(timezone.utc).date()
        conversations = await self.list_conversations(tenant_id)
        leads = await self.list_leads(tenant_id)
        automations = await self.list_automations(tenant_id)
        channels = await self.list_channels(tenant_id)
        tenant = await self._require_tenant(tenant_id)
        notification_settings = await self.notifications.get_or_create_settings(tenant_id)
        notification_counts = await self.notifications.count_events_by_status(tenant_id)
        messages = list(
            (
                await self.session.execute(
                    select(Message).where(Message.tenant_id == tenant_id)
                )
            ).scalars()
        )
        connected_channels = sum(1 for channel in channels if channel.type == "whatsapp" and channel.status == "connected")
        pending_or_connected = any(channel.type == "whatsapp" and channel.status in {"connected", "pending"} for channel in channels)
        ai_receptionist_enabled = any(automation.slug == "ai-receptionist" and automation.enabled for automation in automations)
        has_business_profile = bool((tenant.business_profile or {}).get("businessName"))
        missing: list[str] = []
        if not has_business_profile:
            missing.append("Add a business name")
        if not pending_or_connected:
            missing.append("Connect a WhatsApp channel")
        if notification_settings is None:
            missing.append("Configure notification settings")
        if not ai_receptionist_enabled:
            missing.append("Enable the AI receptionist automation")
        return {
            "connectedWhatsAppNumbers": connected_channels,
            "conversationsToday": sum(
                1 for conversation in conversations if conversation.last_message_at and conversation.last_message_at.date() == today
            ),
            "newLeadsToday": sum(1 for lead in leads if lead.created_at.date() == today),
            "handoffsNeeded": sum(1 for conversation in conversations if conversation.status == "needs_human"),
            "activeAutomations": sum(1 for automation in automations if automation.enabled),
            "pendingNotifications": notification_counts.get("pending", 0),
            "failedNotifications": notification_counts.get("failed", 0),
            "needsHumanConversations": sum(1 for conversation in conversations if conversation.status == "needs_human"),
            "draftMessages": sum(1 for message in messages if message.status == "draft"),
            "connectedChannels": connected_channels,
            "disconnectedChannels": sum(1 for channel in channels if channel.status == "disconnected"),
            "readiness": {
                "hasBusinessProfile": has_business_profile,
                "hasConnectedWhatsApp": pending_or_connected,
                "hasNotificationSettings": notification_settings is not None,
                "hasAiReceptionistEnabled": ai_receptionist_enabled,
                "readyForLiveTest": has_business_profile and pending_or_connected and notification_settings is not None and ai_receptionist_enabled,
                "missing": missing,
            },
        }

    async def simulate_whatsapp_message(
        self,
        tenant_id: int,
        *,
        text: str = "Hi, I want to book an appointment and know the price.",
        contact_name: str = "Demo Customer",
        phone: str = "+15550001111",
    ) -> dict[str, Any]:
        channel = await self.ensure_whatsapp_channel(tenant_id)
        channel.status = "connected"
        channel.last_synced_at = datetime.utcnow()
        result = await self.ingest_inbound_message(
            tenant_id=tenant_id,
            channel_account=channel,
            text=text,
            external_contact_id=phone,
            contact_name=contact_name,
            phone=phone,
            external_message_id=f"dev-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}",
            raw_payload={"source": "dev-simulate"},
        )
        await self.session.commit()
        return result

    async def ingest_evolution_webhook(self, tenant_id: int, channel_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        channel = await self.get_channel(tenant_id, channel_id)
        channel.status = "connected"
        channel.last_synced_at = datetime.utcnow()
        normalized = self._normalize_evolution_payload(payload)
        if normalized.get("ignored"):
            await self.session.commit()
            return {"ok": True, "ignored": True}
        result = await self.ingest_inbound_message(
            tenant_id=tenant_id,
            channel_account=channel,
            text=normalized["text"],
            external_contact_id=normalized["external_contact_id"],
            contact_name=normalized.get("contact_name"),
            phone=normalized.get("phone"),
            external_message_id=normalized.get("external_message_id"),
            raw_payload=payload,
        )
        await self.session.commit()
        return result

    async def ingest_evolution_webhook_for_channel(
        self,
        channel_id: int,
        payload: dict[str, Any],
        *,
        webhook_secret: str | None = None,
    ) -> dict[str, Any]:
        try:
            self.evolution.validate_webhook_secret(webhook_secret)
        except EvolutionWebhookAuthError as exc:
            raise MessagingWebhookAuthError(str(exc)) from exc
        result = await self.session.execute(select(ChannelAccount).where(ChannelAccount.id == channel_id))
        channel = result.scalar_one_or_none()
        if channel is None:
            raise MessagingAuthError("Channel not found")
        return await self.ingest_evolution_webhook(channel.tenant_id, channel_id, payload)

    async def ingest_inbound_message(
        self,
        *,
        tenant_id: int,
        channel_account: ChannelAccount,
        text: str,
        external_contact_id: str,
        contact_name: str | None,
        phone: str | None,
        external_message_id: str | None,
        raw_payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if external_message_id:
            existing_result = await self.session.execute(
                select(Message).where(
                    Message.tenant_id == tenant_id,
                    Message.channel_account_id == channel_account.id,
                    Message.external_message_id == external_message_id,
                )
            )
            existing_message = existing_result.scalar_one_or_none()
            if existing_message is not None:
                return {"ok": True, "ignored": True, "duplicate": True, "conversationId": str(existing_message.conversation_id)}
        contact = await self._get_or_create_contact(
            tenant_id=tenant_id,
            channel_account=channel_account,
            external_contact_id=external_contact_id,
            contact_name=contact_name,
            phone=phone,
        )
        conversation = await self._get_or_create_conversation(
            tenant_id=tenant_id,
            channel_account=channel_account,
            contact=contact,
        )

        message = Message(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            channel_account_id=channel_account.id,
            direction="inbound",
            sender_type="contact",
            status="sent",
            text=text,
            raw_payload=raw_payload,
            external_message_id=external_message_id,
        )
        self.session.add(message)
        await self.session.flush()

        lower_text = text.lower()
        needs_transition = any(keyword in lower_text for keyword in HUMAN_HANDOFF_WORDS)
        if needs_transition:
            await self._mark_conversation_needs_human(conversation, preview_text=text)
        elif conversation.status != "needs_human":
            conversation.status = "ai_active"
        self._touch_conversation(conversation, text=text, inbound=True)

        lead = None
        lead_created = False
        if any(keyword in lower_text for keyword in BOOKING_INTENT_WORDS):
            lead, lead_created = await self._get_or_create_lead(tenant_id=tenant_id, conversation=conversation, contact=contact, text=text)
            if lead_created:
                await self.notifications.notify_new_lead(tenant_id, lead)

        if conversation.status == "ai_active":
            await self._maybe_create_ai_receptionist_reply(
                tenant_id=tenant_id,
                tenant=await self._require_tenant(tenant_id),
                channel_account=channel_account,
                conversation=conversation,
                inbound_message=message,
                contact=contact,
                lead=lead,
            )

        return {
            "ok": True,
            "conversationId": str(conversation.id),
            "messageText": text,
            "leadId": str(lead.id) if lead else None,
        }

    async def _automation_enabled(self, tenant_id: int, slug: str) -> bool:
        automation = await self._get_automation(tenant_id, slug)
        return bool(automation.enabled) if automation else False

    async def _get_automation(self, tenant_id: int, slug: str) -> Automation | None:
        result = await self.session.execute(select(Automation).where(Automation.tenant_id == tenant_id, Automation.slug == slug))
        return result.scalar_one_or_none()

    async def _get_or_create_contact(
        self,
        *,
        tenant_id: int,
        channel_account: ChannelAccount,
        external_contact_id: str,
        contact_name: str | None,
        phone: str | None,
    ) -> Contact:
        result = await self.session.execute(
            select(Contact).where(
                Contact.tenant_id == tenant_id,
                Contact.channel_account_id == channel_account.id,
                Contact.external_contact_id == external_contact_id,
            )
        )
        contact = result.scalar_one_or_none()
        if contact is None:
            contact = Contact(
                tenant_id=tenant_id,
                channel_account_id=channel_account.id,
                external_contact_id=external_contact_id,
                name=contact_name,
                phone=phone,
            )
            self.session.add(contact)
            try:
                await self.session.flush()
            except IntegrityError:
                await self.session.rollback()
                result = await self.session.execute(
                    select(Contact).where(
                        Contact.tenant_id == tenant_id,
                        Contact.channel_account_id == channel_account.id,
                        Contact.external_contact_id == external_contact_id,
                    )
                )
                contact = result.scalar_one()
        else:
            if contact_name:
                contact.name = contact_name
            if phone:
                contact.phone = phone
        return contact

    async def _get_or_create_conversation(
        self,
        *,
        tenant_id: int,
        channel_account: ChannelAccount,
        contact: Contact,
    ) -> Conversation:
        result = await self.session.execute(
            select(Conversation).where(
                Conversation.tenant_id == tenant_id,
                Conversation.channel_account_id == channel_account.id,
                Conversation.contact_id == contact.id,
            )
        )
        conversation = result.scalar_one_or_none()
        if conversation is None:
            conversation = Conversation(
                tenant_id=tenant_id,
                channel_account_id=channel_account.id,
                channel=channel_account.type,
                contact_id=contact.id,
                status="ai_active",
                latest_message_text="",
                unread_count=0,
            )
            self.session.add(conversation)
            try:
                await self.session.flush()
            except IntegrityError:
                await self.session.rollback()
                result = await self.session.execute(
                    select(Conversation).where(
                        Conversation.tenant_id == tenant_id,
                        Conversation.channel_account_id == channel_account.id,
                        Conversation.contact_id == contact.id,
                    )
                )
                conversation = result.scalar_one()
        return conversation

    async def _get_or_create_lead(self, *, tenant_id: int, conversation: Conversation, contact: Contact, text: str) -> tuple[Lead, bool]:
        result = await self.session.execute(
            select(Lead).where(
                Lead.tenant_id == tenant_id,
                Lead.conversation_id == conversation.id,
            )
        )
        lead = result.scalar_one_or_none()
        service_name = self._guess_service(text)
        created = False
        if lead is None:
            lead = Lead(
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                name=contact.name,
                phone=contact.phone,
                service=service_name,
                status="new",
                source="whatsapp",
            )
            self.session.add(lead)
            try:
                await self.session.flush()
            except IntegrityError:
                await self.session.rollback()
                result = await self.session.execute(
                    select(Lead).where(
                        Lead.tenant_id == tenant_id,
                        Lead.conversation_id == conversation.id,
                    )
                )
                existing = result.scalar_one_or_none()
                if existing is not None:
                    return existing, False
                raise
            created = True
        else:
            lead.name = contact.name or lead.name
            lead.phone = contact.phone or lead.phone
            lead.service = service_name or lead.service
            lead.status = "new"
            lead.updated_at = datetime.utcnow()

        await self._create_skill_run(tenant_id, "capture-lead", conversation.id)
        return lead, created

    async def _resolve_skill(self, identifier: str) -> Skill:
        stmt: Select[tuple[Skill]]
        if identifier.isdigit():
            stmt = select(Skill).where(Skill.id == int(identifier))
        else:
            stmt = select(Skill).where(Skill.slug == identifier)
        result = await self.session.execute(stmt)
        skill = result.scalar_one_or_none()
        if skill is not None:
            return skill
        automation = None
        if identifier.isdigit():
            result = await self.session.execute(select(Automation).where(Automation.id == int(identifier)))
            automation = result.scalar_one_or_none()
        if automation is not None:
            result = await self.session.execute(select(Skill).where(or_(Skill.slug == automation.slug, Skill.name == automation.name)))
            skill = result.scalar_one_or_none()
            if skill is not None:
                return skill
        raise MessagingAuthError("Skill not found")

    async def _create_skill_run(self, tenant_id: int, skill_identifier: str, conversation_id: int | None = None) -> SkillRun:
        skill = await self._resolve_skill(skill_identifier)
        skill_run = SkillRun(
            tenant_id=tenant_id,
            skill_id=skill.id,
            conversation_id=conversation_id,
            input={"source": "automation", "skillIdentifier": skill_identifier},
            output={"ok": True, "skill": skill.slug},
            status="success",
        )
        self.session.add(skill_run)
        await self.session.flush()
        return skill_run

    async def _require_conversation(self, tenant_id: int, conversation_id: int) -> Conversation:
        result = await self.session.execute(select(Conversation).where(Conversation.id == conversation_id))
        conversation = result.scalar_one_or_none()
        if conversation is None or conversation.tenant_id != tenant_id:
            raise MessagingAuthError("Conversation not found")
        return conversation

    async def _require_contact(self, contact_id: int) -> Contact:
        result = await self.session.execute(select(Contact).where(Contact.id == contact_id))
        contact = result.scalar_one_or_none()
        if contact is None:
            raise MessagingAuthError("Contact not found")
        return contact

    async def _require_tenant(self, tenant_id: int) -> Tenant:
        result = await self.session.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = result.scalar_one_or_none()
        if tenant is None:
            raise MessagingAuthError("Tenant not found")
        return tenant

    async def _ensure_tenant_for_user(self, user: User) -> Tenant:
        result = await self.session.execute(select(Tenant).where(Tenant.owner_user_id == user.id).order_by(Tenant.id))
        tenant = result.scalar_one_or_none()
        if tenant is None:
            tenant = Tenant(
                owner_user_id=user.id,
                name=(user.full_name or user.username or user.email or "My Business").strip() or "My Business",
                business_profile=DEFAULT_BUSINESS_PROFILE.copy(),
            )
            self.session.add(tenant)
            await self.session.flush()
        await self._ensure_default_automations(tenant)
        await self._ensure_default_skills()
        return tenant

    async def _ensure_default_automations(self, tenant: Tenant) -> None:
        existing = {
            automation.slug: automation
            for automation in (
                await self.session.execute(select(Automation).where(Automation.tenant_id == tenant.id))
            ).scalars()
        }
        created = False
        for item in DEFAULT_AUTOMATIONS:
            if item["slug"] in existing:
                default_config = self._default_automation_config(item["slug"])
                if default_config:
                    current_config = existing[item["slug"]].config or {}
                    merged_config = {**default_config, **current_config}
                    if merged_config != current_config:
                        existing[item["slug"]].config = merged_config
                continue
            self.session.add(Automation(tenant_id=tenant.id, **item, config=self._default_automation_config(item["slug"])))
            created = True
        if created:
            await self.session.flush()

    async def _maybe_create_ai_receptionist_reply(
        self,
        *,
        tenant_id: int,
        tenant: Tenant,
        channel_account: ChannelAccount,
        conversation: Conversation,
        inbound_message: Message,
        contact: Contact,
        lead: Lead | None,
    ) -> None:
        automation = await self._get_automation(tenant_id, "ai-receptionist")
        if automation is None or not automation.enabled or not self.ai_receptionist.enabled:
            return

        business_profile = tenant.business_profile or DEFAULT_BUSINESS_PROFILE
        recent_messages = await self._list_recent_messages(conversation.id, tenant_id)
        decision = await self.ai_receptionist.generate_reply(
            tenant,
            business_profile,
            conversation,
            recent_messages,
            inbound_message,
        )
        if lead is not None and decision.lead_patch:
            await self._apply_lead_patch(lead, decision.lead_patch)

        status = "draft"
        raw_payload: dict[str, Any] = {
            "source": "ai_receptionist",
            "reason": decision.reason,
            "confidence": decision.confidence,
            "safetyCategory": decision.safety_category,
            "autoSendRequested": False,
        }

        if decision.should_handoff:
            await self._mark_conversation_needs_human(conversation, preview_text=inbound_message.text)
        elif await self._should_auto_send_ai_reply(automation, channel_account):
            raw_payload["autoSendRequested"] = True
            delivery = await self._deliver_outbound_message(
                channel=channel_account,
                contact=contact,
                text=decision.reply_text,
                source="ai_receptionist",
            )
            status = delivery["status"]
            raw_payload["delivery"] = delivery
            if status == "failed":
                await self._mark_conversation_needs_human(conversation, preview_text=decision.reply_text)

        ai_message = Message(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            channel_account_id=channel_account.id,
            direction="outbound",
            sender_type="ai",
            status=status,
            text=decision.reply_text,
            raw_payload=raw_payload,
            external_message_id=(raw_payload.get("delivery") or {}).get("messageId"),
        )
        self.session.add(ai_message)

    async def _list_recent_messages(self, conversation_id: int, tenant_id: int, limit: int = 8) -> list[Message]:
        messages = list(
            (
                await self.session.execute(
                    select(Message)
                    .where(Message.conversation_id == conversation_id, Message.tenant_id == tenant_id)
                    .order_by(Message.created_at.desc(), Message.id.desc())
                    .limit(limit)
                )
            ).scalars()
        )
        return list(reversed(messages))

    async def _apply_lead_patch(self, lead: Lead, patch: dict[str, Any]) -> None:
        for key in ("name", "phone", "service", "preferred_time", "status"):
            if key in patch and patch[key]:
                setattr(lead, key, patch[key])
        lead.updated_at = datetime.utcnow()

    async def _should_auto_send_ai_reply(self, automation: Automation, channel_account: ChannelAccount) -> bool:
        automation_config = automation.config or {}
        channel_config = channel_account.credentials_encrypted or {}
        if "aiAutoSend" in channel_config:
            return bool(channel_config["aiAutoSend"])
        if "autoSend" in automation_config:
            return bool(automation_config["autoSend"])
        return bool(self.settings.ai_auto_send_default)

    def _default_automation_config(self, slug: str) -> dict[str, Any]:
        if slug != "ai-receptionist":
            return {}
        return {
            "autoSend": False,
            "handoffKeywords": list(HUMAN_HANDOFF_WORDS),
        }

    async def _mark_conversation_needs_human(self, conversation: Conversation, *, preview_text: str | None = None) -> None:
        already_needs_human = conversation.status == "needs_human"
        conversation.status = "needs_human"
        conversation.updated_at = datetime.utcnow()
        if not already_needs_human:
            await self.notifications.notify_needs_human(conversation.tenant_id, conversation, preview_text=preview_text)

    async def _deliver_outbound_message(
        self,
        *,
        channel: ChannelAccount,
        contact: Contact,
        text: str,
        source: str,
    ) -> dict[str, Any]:
        if self.evolution.enabled and channel.type == "whatsapp" and channel.external_account_id:
            try:
                delivery = await self.evolution.send_message(
                    channel,
                    to=contact.phone or contact.external_contact_id,
                    text=text,
                )
            except EvolutionApiError as exc:
                return {"provider": "evolution", "status": "failed", "error": str(exc), "source": source}
            return {
                "provider": delivery.get("provider", "evolution"),
                "instance": delivery.get("instance"),
                "messageId": delivery.get("messageId"),
                "status": "sent",
                "source": source,
            }
        return {"provider": "mock", "status": "sent", "source": source}

    def _ensure_draft_editable(self, message: Message) -> None:
        if message.status != "draft":
            raise MessagingAuthError("Only draft messages can be edited or discarded")
        if message.direction != "outbound":
            raise MessagingAuthError("Only outbound draft messages can be edited or discarded")

    def _ensure_draft_sendable(self, message: Message) -> None:
        self._ensure_draft_editable(message)

    async def _ensure_default_skills(self) -> None:
        for item in DEFAULT_SKILLS:
            # Handle idempotency via dialect-specific UPSERT
            if self.session.bind.dialect.name == "postgresql":
                stmt = pg_insert(Skill).values(**item)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["slug"],
                    set_={k: v for k, v in item.items() if k not in {"slug", "created_at"}},
                )
            else:
                stmt = sqlite_insert(Skill).values(**item)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["slug"],
                    set_={k: v for k, v in item.items() if k not in {"slug", "created_at"}},
                )

            await self.session.execute(stmt)

        await self.session.flush()

    async def _get_user_by_telegram_id(self, telegram_user_id: int) -> User | None:
        result = await self.session.execute(select(User).where(User.tg_user_id == telegram_user_id))
        return result.scalar_one_or_none()

    async def _get_user_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(func.lower(func.coalesce(User.email, "")) == email.strip().lower()))
        return result.scalar_one_or_none()

    def _resolve_telegram_identity(self, init_data: str | None, app_boundary: str | None = None) -> TelegramWebAppIdentity:
        if init_data:
            return verify_telegram_init_data_identity(init_data)

        parsed = dict(parse_qsl("", keep_blank_values=True))
        user_raw = parsed.get("user")
        user = {}
        if user_raw:
            try:
                user = json.loads(user_raw)
            except json.JSONDecodeError as exc:
                raise TelegramWebAppAuthError("Malformed Telegram user payload") from exc

        user_id = int(user.get("id") or parsed.get("dev_user_id") or 900001)
        return TelegramWebAppIdentity(
            user_id=user_id,
            username=str(user.get("username") or parsed.get("username") or f"dev_user_{user_id}"),
            first_name=str(user.get("first_name") or "Dev"),
            last_name=str(user.get("last_name") or "User"),
            auth_date=int(datetime.utcnow().timestamp()),
            raw={"auth_type": "dev"},
        )

    def _touch_conversation(self, conversation: Conversation, *, text: str, inbound: bool) -> None:
        now = datetime.utcnow()
        conversation.latest_message_text = text
        conversation.last_message_at = now
        conversation.updated_at = now
        if inbound:
            conversation.unread_count += 1

    def _create_token_for_user(self, user: User) -> str:
        identity = TelegramWebAppIdentity(
            user_id=user.id,
            username=user.username,
            first_name=user.full_name,
            last_name=None,
            auth_date=int(datetime.utcnow().timestamp()),
            raw={"auth_type": "session"},
        )
        return create_dashboard_jwt(identity, expires_in_seconds=self.settings.dashboard_jwt_exp_seconds)

    def _hash_password(self, password: str) -> str:
        secret = self.settings.dashboard_jwt_secret or self.settings.bot_token
        if not secret:
            raise RuntimeError("Cannot hash password: no dashboard_jwt_secret or bot_token configured")
        return hashlib.sha256(secret.encode("utf-8") + password.encode("utf-8")).hexdigest()

    def _full_name(self, first_name: str | None, last_name: str | None) -> str | None:
        value = " ".join(part for part in [first_name, last_name] if part).strip()
        return value or None

    def _guess_service(self, text: str) -> str | None:
        lowered = text.lower()
        for keyword in ("cleaning", "consultation", "repair", "installation", "demo", "trial"):
            if keyword in lowered:
                return keyword
        return None

    def _mock_qr_svg(self, label: str) -> str:
        svg = f"""
        <svg xmlns="http://www.w3.org/2000/svg" width="220" height="220" viewBox="0 0 220 220">
          <rect width="220" height="220" rx="24" fill="#ffffff" />
          <rect x="22" y="22" width="176" height="176" rx="18" fill="#111827" />
          <rect x="38" y="38" width="44" height="44" fill="#25D366" />
          <rect x="138" y="38" width="44" height="44" fill="#25D366" />
          <rect x="38" y="138" width="44" height="44" fill="#25D366" />
          <path d="M106 54h20v20h-20zm0 36h56v20h-20v20h20v20h-56v-20h20v-20h-20z" fill="#E5E7EB"/>
          <text x="110" y="204" text-anchor="middle" font-size="14" font-family="Arial" fill="#111827">{label}</text>
        </svg>
        """.strip()
        return f"data:image/svg+xml;base64,{base64.b64encode(svg.encode('utf-8')).decode('ascii')}"

    def _normalize_evolution_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        event = str(payload.get("event") or data.get("event") or "").lower() if isinstance(data, dict) else ""
        message = data.get("message") if isinstance(data.get("message"), dict) else data
        nested_message = message.get("message") if isinstance(message, dict) and isinstance(message.get("message"), dict) else None
        key = message.get("key") if isinstance(message, dict) and isinstance(message.get("key"), dict) else {}
        from_me = bool(
            key.get("fromMe")
            or (data.get("fromMe") if isinstance(data, dict) else False)
            or (message.get("fromMe") if isinstance(message, dict) else False)
        )
        if from_me:
            return {"ignored": True, "reason": "from_me"}
        text = self._extract_evolution_text(message, nested_message)
        if not text or not text.strip():
            return {"ignored": True, "reason": "non_text_event", "event": event}
        external_contact_id = (
            key.get("remoteJid")
            or (data.get("remoteJid") if isinstance(data, dict) else None)
            or (data.get("from") if isinstance(data, dict) else None)
            or (data.get("sender") if isinstance(data, dict) else None)
            or "unknown-contact"
        )
        phone = external_contact_id.replace("@s.whatsapp.net", "") if isinstance(external_contact_id, str) else None
        contact_name = (
            (data.get("pushName") if isinstance(data, dict) else None)
            or (data.get("senderName") if isinstance(data, dict) else None)
            or (data.get("contactName") if isinstance(data, dict) else None)
        )
        external_message_id = (
            key.get("id")
            or (data.get("messageId") if isinstance(data, dict) else None)
            or (data.get("id") if isinstance(data, dict) else None)
        )
        return {
            "text": str(text),
            "external_contact_id": str(external_contact_id),
            "contact_name": str(contact_name) if contact_name else None,
            "phone": phone,
            "external_message_id": str(external_message_id) if external_message_id else None,
        }

    def _extract_evolution_text(self, message: dict[str, Any] | Any, nested_message: dict[str, Any] | None) -> str | None:
        candidates: list[Any] = []
        if isinstance(message, dict):
            candidates.extend(
                [
                    message.get("text"),
                    message.get("conversation"),
                    (message.get("extendedTextMessage") or {}).get("text")
                    if isinstance(message.get("extendedTextMessage"), dict)
                    else None,
                    (message.get("imageMessage") or {}).get("caption")
                    if isinstance(message.get("imageMessage"), dict)
                    else None,
                ]
            )
        if isinstance(nested_message, dict):
            candidates.extend(
                [
                    nested_message.get("text"),
                    nested_message.get("conversation"),
                    (nested_message.get("extendedTextMessage") or {}).get("text")
                    if isinstance(nested_message.get("extendedTextMessage"), dict)
                    else None,
                    (nested_message.get("imageMessage") or {}).get("caption")
                    if isinstance(nested_message.get("imageMessage"), dict)
                    else None,
                ]
            )
        for candidate in candidates:
            if candidate is None:
                continue
            value = str(candidate).strip()
            if value:
                return value
        return None
