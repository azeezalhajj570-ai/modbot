from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

import httpx

from bot.ai.providers import AIProviderError
from bot.config import Settings, get_settings
from bot.db.models import Conversation, Message, Tenant


SAFETY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "medical": ("diagnosis", "diagnose", "symptom", "symptoms", "prescription", "medical advice"),
    "emergency": ("emergency", "urgent", "ambulance", "bleeding", "can't breathe", "cannot breathe", "chest pain"),
    "legal": ("legal advice", "lawyer", "sue", "lawsuit", "attorney"),
    "financial": ("financial advice", "investment advice", "tax advice", "loan advice"),
    "refund": ("refund", "chargeback", "dispute"),
    "complaint": ("complaint", "manager", "escalate"),
    "human": ("human", "agent", "person", "representative", "support"),
}


@dataclass
class AIReceptionistDecision:
    reply_text: str
    should_handoff: bool
    confidence: float
    reason: str
    lead_patch: dict[str, Any] | None = None
    safety_category: str | None = None


class BaseAIReceptionistProvider:
    async def generate(
        self,
        *,
        business_profile: dict[str, Any],
        recent_messages: list[Message],
        inbound_message: Message,
    ) -> AIReceptionistDecision:
        raise NotImplementedError


class MockAIReceptionistProvider(BaseAIReceptionistProvider):
    async def generate(
        self,
        *,
        business_profile: dict[str, Any],
        recent_messages: list[Message],
        inbound_message: Message,
    ) -> AIReceptionistDecision:
        del recent_messages

        lowered = inbound_message.text.lower()
        business_name = (business_profile.get("businessName") or "our team").strip() or "our team"
        category = (business_profile.get("category") or "business").strip() or "business"
        booking_link = (business_profile.get("bookingLink") or "").strip()
        escalation_contact = (business_profile.get("escalationContact") or "").strip()
        faqs = business_profile.get("faqs") or []

        safety_category = _detect_safety_category(lowered)
        if safety_category in {"medical", "emergency"}:
            return AIReceptionistDecision(
                reply_text=_medical_handoff_text(escalation_contact),
                should_handoff=True,
                confidence=0.99,
                reason="medical_or_emergency_handoff",
                safety_category=safety_category,
            )
        if safety_category in {"legal", "financial", "refund", "complaint", "human"}:
            return AIReceptionistDecision(
                reply_text=_human_handoff_text(escalation_contact),
                should_handoff=True,
                confidence=0.98,
                reason=f"{safety_category}_handoff",
                safety_category=safety_category,
            )

        faq_answer = _match_faq_answer(lowered, faqs)
        if faq_answer:
            return AIReceptionistDecision(
                reply_text=f"Thanks for messaging {business_name}. {faq_answer} Is there anything else you'd like to know?",
                should_handoff=False,
                confidence=0.84,
                reason="faq_match",
            )

        matched_service = _match_service(lowered, business_profile.get("services") or [])
        asks_price = any(word in lowered for word in ("price", "cost", "pricing", "quote", "how much"))
        asks_booking = any(word in lowered for word in ("book", "booking", "appointment", "schedule"))

        if asks_price:
            if matched_service and matched_service.get("priceFrom"):
                service_name = matched_service.get("name") or "that service"
                price_from = str(matched_service["priceFrom"]).strip()
                return AIReceptionistDecision(
                    reply_text=(
                        f"Thanks for contacting {business_name}. {service_name} starts from {price_from}. "
                        "If you'd like, please share your name and preferred time and our team can help from there."
                    ),
                    should_handoff=False,
                    confidence=0.9,
                    reason="service_price_from_profile",
                    lead_patch={"service": matched_service.get("name")},
                )
            return AIReceptionistDecision(
                reply_text=(
                    f"Thanks for contacting {business_name}. I don't have a confirmed price to share here, "
                    "but our team can confirm pricing for you. If you'd like, please share your name and the service you're interested in."
                ),
                should_handoff=False,
                confidence=0.74,
                reason="price_missing_from_profile",
            )

        if asks_booking:
            if booking_link:
                return AIReceptionistDecision(
                    reply_text=(
                        f"Thanks for contacting {business_name}. You can request a booking here: {booking_link}. "
                        "If you'd like, please share your name and preferred time as well."
                    ),
                    should_handoff=False,
                    confidence=0.88,
                    reason="booking_link_available",
                )
            return AIReceptionistDecision(
                reply_text=(
                    f"Thanks for contacting {business_name}. I can help note your interest for the team. "
                    "Please share your name and preferred time, and they can follow up with booking details."
                ),
                should_handoff=False,
                confidence=0.76,
                reason="booking_without_link",
            )

        opening_hours = (business_profile.get("openingHours") or "").strip()
        if opening_hours and any(word in lowered for word in ("open", "hours", "time", "close")):
            return AIReceptionistDecision(
                reply_text=(
                    f"Thanks for contacting {business_name}. Our listed opening hours are {opening_hours}. "
                    "How can I help you next?"
                ),
                should_handoff=False,
                confidence=0.86,
                reason="opening_hours_from_profile",
            )

        return AIReceptionistDecision(
            reply_text=(
                f"Thanks for messaging {business_name}. We're a {category}, and I'm happy to help with general questions "
                "based on our business information. What service are you interested in?"
            ),
            should_handoff=False,
            confidence=0.62,
            reason="generic_profile_reply",
        )


class OpenAIReceptionistProvider(BaseAIReceptionistProvider):
    def __init__(self, api_key: str, model: str, timeout_seconds: float) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def generate(
        self,
        *,
        business_profile: dict[str, Any],
        recent_messages: list[Message],
        inbound_message: Message,
    ) -> AIReceptionistDecision:
        prompt = _build_model_prompt(business_profile, recent_messages, inbound_message)
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": self.model,
            "input": [
                {"role": "system", "content": _system_instructions()},
                {"role": "user", "content": prompt},
            ],
            "text": {"format": {"type": "json_object"}},
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post("https://api.openai.com/v1/responses", headers=headers, json=payload)
        if response.status_code >= 400:
            raise AIProviderError(f"openai_http_{response.status_code}")
        data = response.json()
        output = data.get("output", [])
        if not output:
            raise AIProviderError("openai_empty_output")
        content = output[0].get("content", [])
        if not content:
            raise AIProviderError("openai_missing_content")
        parsed = content[0].get("parsed") or content[0].get("text") or "{}"
        if isinstance(parsed, str):
            parsed = json.loads(parsed)
        return _decision_from_payload(parsed)


class GeminiReceptionistProvider(BaseAIReceptionistProvider):
    def __init__(self, api_key: str, model: str, timeout_seconds: float) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def generate(
        self,
        *,
        business_profile: dict[str, Any],
        recent_messages: list[Message],
        inbound_message: Message,
    ) -> AIReceptionistDecision:
        prompt = _system_instructions() + "\n\n" + _build_model_prompt(business_profile, recent_messages, inbound_message)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"response_mime_type": "application/json"},
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(url, json=payload)
        if response.status_code >= 400:
            raise AIProviderError(f"gemini_http_{response.status_code}")
        data = response.json()
        candidates = data.get("candidates", [])
        if not candidates:
            raise AIProviderError("gemini_empty_output")
        text_out = candidates[0]["content"]["parts"][0].get("text", "{}")
        return _decision_from_payload(json.loads(text_out))


class AIReceptionistService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.provider_name = (self.settings.ai_provider or "mock").strip().lower()
        self.model = (
            self.settings.ai_model
            or self.settings.openai_model
            or self.settings.gemini_model
            or "gpt-4.1-mini"
        )
        self.timeout_seconds = self.settings.ai_request_timeout_seconds
        self._provider = self._build_provider()

    @property
    def enabled(self) -> bool:
        return bool(self.settings.ai_receptionist_enabled)

    async def generate_reply(
        self,
        tenant: Tenant,
        business_profile: dict[str, Any],
        conversation: Conversation,
        recent_messages: list[Message],
        inbound_message: Message,
    ) -> AIReceptionistDecision:
        del tenant, conversation
        try:
            return await self._provider.generate(
                business_profile=business_profile,
                recent_messages=recent_messages,
                inbound_message=inbound_message,
            )
        except (AIProviderError, ValueError, KeyError, IndexError, httpx.HTTPError):
            mock_provider = MockAIReceptionistProvider()
            return await mock_provider.generate(
                business_profile=business_profile,
                recent_messages=recent_messages,
                inbound_message=inbound_message,
            )

    def _build_provider(self) -> BaseAIReceptionistProvider:
        provider_name = self.provider_name
        if provider_name == "openai" and self.settings.openai_api_key:
            return OpenAIReceptionistProvider(
                api_key=self.settings.openai_api_key,
                model=self.settings.ai_model or self.settings.openai_model,
                timeout_seconds=self.timeout_seconds,
            )
        if provider_name == "gemini" and self.settings.gemini_api_key:
            return GeminiReceptionistProvider(
                api_key=self.settings.gemini_api_key,
                model=self.settings.ai_model or self.settings.gemini_model,
                timeout_seconds=self.timeout_seconds,
            )
        return MockAIReceptionistProvider()


def _detect_safety_category(lowered_text: str) -> str | None:
    for category, keywords in SAFETY_KEYWORDS.items():
        if any(keyword in lowered_text for keyword in keywords):
            return category
    return None


def _match_service(lowered_text: str, services: list[dict[str, Any]]) -> dict[str, Any] | None:
    for service in services:
        name = str(service.get("name") or "").strip()
        if name and name.lower() in lowered_text:
            return service
    return services[0] if len(services) == 1 and any(word in lowered_text for word in ("price", "cost", "book", "service")) else None


def _match_faq_answer(lowered_text: str, faqs: list[dict[str, Any]]) -> str | None:
    for faq in faqs:
        question = str(faq.get("question") or "").strip().lower()
        answer = str(faq.get("answer") or "").strip()
        if not question or not answer:
            continue
        question_terms = [term for term in question.replace("?", " ").split() if len(term) > 3]
        if question_terms and all(term in lowered_text for term in question_terms[:2]):
            return answer
    return None


def _human_handoff_text(escalation_contact: str) -> str:
    suffix = f" You can also contact our team at {escalation_contact}." if escalation_contact else ""
    return f"Thanks for your message. I've marked this conversation for a team member to follow up with you shortly.{suffix}"


def _medical_handoff_text(escalation_contact: str) -> str:
    suffix = f" You can also contact our team at {escalation_contact}." if escalation_contact else ""
    return (
        "Thanks for your message. I can't provide diagnosis, emergency help, or medical advice over chat. "
        "If this is urgent, please contact local emergency services or a qualified professional right away."
        f"{suffix}"
    )


def _system_instructions() -> str:
    return (
        "You are a safety-first WhatsApp AI receptionist. Reply only from the provided business profile and recent conversation context. "
        "Never invent prices, services, opening hours, booking availability, medical/legal/financial advice, or internal system details. "
        "If the user needs medical, legal, financial, refund, complaint escalation, or human support, set shouldHandoff=true. "
        "Return JSON with keys: replyText, shouldHandoff, confidence, reason, leadPatch, safetyCategory."
    )


def _build_model_prompt(
    business_profile: dict[str, Any],
    recent_messages: list[Message],
    inbound_message: Message,
) -> str:
    recent_payload = [
        {"direction": message.direction, "senderType": message.sender_type, "text": message.text}
        for message in recent_messages[-8:]
    ]
    return json.dumps(
        {
            "businessProfile": business_profile,
            "recentMessages": recent_payload,
            "latestInboundMessage": inbound_message.text,
        },
        ensure_ascii=True,
    )


def _decision_from_payload(payload: dict[str, Any]) -> AIReceptionistDecision:
    reply_text = str(payload.get("replyText") or payload.get("reply_text") or "").strip()[:4096]
    if not reply_text:
        raise AIProviderError("empty_reply_text")
    return AIReceptionistDecision(
        reply_text=reply_text,
        should_handoff=bool(payload.get("shouldHandoff") or payload.get("should_handoff")),
        confidence=float(payload.get("confidence", 0.5)),
        reason=str(payload.get("reason") or "model_response"),
        lead_patch=payload.get("leadPatch") if isinstance(payload.get("leadPatch"), dict) else None,
        safety_category=str(payload["safetyCategory"]) if payload.get("safetyCategory") else None,
    )
