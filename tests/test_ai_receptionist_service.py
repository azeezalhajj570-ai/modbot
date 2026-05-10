from __future__ import annotations

from datetime import datetime

import pytest

from bot.db.models import Conversation, Message, Tenant
from bot.services.ai_receptionist_service import AIReceptionistService


def _tenant(profile: dict) -> Tenant:
    return Tenant(id=1, owner_user_id=1, name="Demo", business_profile=profile)


def _conversation() -> Conversation:
    return Conversation(
        id=1,
        tenant_id=1,
        channel_account_id=1,
        channel="whatsapp",
        contact_id=1,
        status="ai_active",
        latest_message_text="",
        unread_count=0,
    )


def _message(text: str) -> Message:
    return Message(
        id=1,
        tenant_id=1,
        conversation_id=1,
        channel_account_id=1,
        direction="inbound",
        sender_type="contact",
        status="sent",
        text=text,
        created_at=datetime.utcnow(),
    )


@pytest.mark.asyncio
async def test_mock_ai_uses_business_profile_price() -> None:
    service = AIReceptionistService()
    decision = await service.generate_reply(
        _tenant(
            {
                "businessName": "Bright Dental",
                "category": "dental clinic",
                "services": [{"name": "Cleaning", "priceFrom": "$120"}],
                "bookingLink": "",
                "faqs": [],
                "forbiddenClaims": [],
            }
        ),
        {
            "businessName": "Bright Dental",
            "category": "dental clinic",
            "services": [{"name": "Cleaning", "priceFrom": "$120"}],
            "bookingLink": "",
            "faqs": [],
            "forbiddenClaims": [],
        },
        _conversation(),
        [],
        _message("What is the price for cleaning?"),
    )
    assert "$120" in decision.reply_text
    assert decision.should_handoff is False


@pytest.mark.asyncio
async def test_mock_ai_does_not_invent_missing_price() -> None:
    service = AIReceptionistService()
    profile = {
        "businessName": "Bright Dental",
        "category": "dental clinic",
        "services": [{"name": "Cleaning"}],
        "bookingLink": "",
        "faqs": [],
        "forbiddenClaims": [],
    }
    decision = await service.generate_reply(_tenant(profile), profile, _conversation(), [], _message("What is the price for cleaning?"))
    assert "confirm pricing" in decision.reply_text.lower()
    assert "$" not in decision.reply_text


@pytest.mark.asyncio
async def test_mock_ai_booking_uses_booking_link() -> None:
    service = AIReceptionistService()
    profile = {
        "businessName": "Studio One",
        "category": "salon",
        "services": [],
        "bookingLink": "https://booking.example.com",
        "faqs": [],
        "forbiddenClaims": [],
    }
    decision = await service.generate_reply(_tenant(profile), profile, _conversation(), [], _message("I want to book"))
    assert "https://booking.example.com" in decision.reply_text
    assert decision.should_handoff is False


@pytest.mark.asyncio
async def test_mock_ai_handoffs_medical_or_emergency_messages() -> None:
    service = AIReceptionistService()
    profile = {
        "businessName": "Care Desk",
        "category": "clinic",
        "services": [],
        "bookingLink": "",
        "faqs": [],
        "forbiddenClaims": [],
    }
    decision = await service.generate_reply(
        _tenant(profile),
        profile,
        _conversation(),
        [],
        _message("This is an emergency and I need a diagnosis"),
    )
    assert decision.should_handoff is True
    assert decision.safety_category in {"medical", "emergency"}


@pytest.mark.asyncio
async def test_mock_ai_handoffs_human_request() -> None:
    service = AIReceptionistService()
    profile = {
        "businessName": "Care Desk",
        "category": "clinic",
        "services": [],
        "bookingLink": "",
        "escalationContact": "+15550001111",
        "faqs": [],
        "forbiddenClaims": [],
    }
    decision = await service.generate_reply(_tenant(profile), profile, _conversation(), [], _message("I need a human agent"))
    assert decision.should_handoff is True
    assert "+15550001111" in decision.reply_text
