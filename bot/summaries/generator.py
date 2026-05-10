from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
import json
import logging

import httpx

from bot.ai.providers import AIProviderError
from bot.config import get_settings
from bot.db.models import Group, GroupSummarySettings
from bot.summaries.schemas import DailyActivityReport, DailySummaryResult

logger = logging.getLogger(__name__)


class SummaryGenerator(ABC):
    @abstractmethod
    async def generate_daily_summary(
        self,
        group: Group,
        settings: GroupSummarySettings,
        activity: DailyActivityReport,
        moderation_events: list[str] | None = None,
    ) -> DailySummaryResult:
        raise NotImplementedError


class DeterministicSummaryGenerator(SummaryGenerator):
    async def generate_daily_summary(
        self,
        group: Group,
        settings: GroupSummarySettings,
        activity: DailyActivityReport,
        moderation_events: list[str] | None = None,
    ) -> DailySummaryResult:
        include_moderation = settings.include_moderation_events if settings.include_moderation_events is not None else True
        include_recommendations = settings.include_recommendations if settings.include_recommendations is not None else True
        include_unanswered = (
            settings.include_unanswered_questions if settings.include_unanswered_questions is not None else True
        )
        topics = activity.top_topics or ["general group activity"]
        topic_text = ", ".join(topics[:3])
        activity_level = "high" if activity.total_messages >= 100 else "moderate" if activity.total_messages >= 25 else "light"
        overview = (
            f"Today the group focused on {topic_text}. Activity was {activity_level}"
            f" with {activity.total_messages} messages from {activity.active_users_count} active users."
        )
        moderation_highlights = activity.moderation_highlights if include_moderation else []
        recommendations: list[str] = []
        if include_recommendations:
            if activity.unanswered_questions:
                recommendations.append("Answer or pin guidance for the unanswered questions.")
            if activity.repeated_questions:
                recommendations.append("Turn repeated questions into a short FAQ or pinned answer.")
            if activity.suspicious_messages_count:
                recommendations.append(f"Review {activity.suspicious_messages_count} suspicious moderation events.")
            if activity.links_count >= 10:
                recommendations.append("Verify frequently shared links and pin trusted resources.")
            if not recommendations:
                recommendations.append("No urgent admin action was detected today.")

        lines = [
            f"Daily Summary — {group.title}",
            "",
            "Overview:",
            overview,
            "",
            "Stats:",
            f"- Messages: {activity.total_messages}",
            f"- Active users: {activity.active_users_count}",
            f"- Links shared: {activity.links_count}",
            f"- Suspicious messages: {activity.suspicious_messages_count}",
            f"- Deleted messages: {activity.deleted_messages_count}",
        ]
        if topics:
            lines.extend(["", "Top Topics:"])
            lines.extend(f"{index}. {topic}" for index, topic in enumerate(topics[:5], start=1))
        if activity.important_questions:
            lines.extend(["", "Important Questions:"])
            lines.extend(f"- {question}" for question in activity.important_questions[:5])
        if include_unanswered and activity.unanswered_questions:
            lines.extend(["", "Unanswered Questions:"])
            lines.extend(f"- {question}" for question in activity.unanswered_questions[:5])
        if moderation_highlights:
            lines.extend(["", "Moderation Highlights:"])
            lines.extend(f"- {item}" for item in moderation_highlights[:5])
        if recommendations:
            lines.extend(["", "Recommended Admin Actions:"])
            lines.extend(f"- {item}" for item in recommendations[:5])

        return DailySummaryResult(
            overview=overview,
            top_topics=topics[:5],
            important_questions=activity.important_questions[:5],
            unanswered_questions=activity.unanswered_questions[:5] if include_unanswered else [],
            moderation_highlights=moderation_highlights[:5],
            recommendations=recommendations[:5],
            summary_text="\n".join(lines),
        )


class LLMSummaryGenerator(SummaryGenerator):
    def __init__(self, *, provider_name: str, api_key: str, model: str) -> None:
        self.provider_name = provider_name
        self.api_key = api_key
        self.model = model

    async def generate_daily_summary(
        self,
        group: Group,
        settings: GroupSummarySettings,
        activity: DailyActivityReport,
        moderation_events: list[str] | None = None,
    ) -> DailySummaryResult:
        prompt = {
            "group_title": group.title,
            "delivery_mode": settings.delivery_mode,
            "activity": {
                "total_messages": activity.total_messages,
                "active_users_count": activity.active_users_count,
                "links_count": activity.links_count,
                "suspicious_messages_count": activity.suspicious_messages_count,
                "deleted_messages_count": activity.deleted_messages_count,
                "top_users": activity.top_users,
                "top_topics": activity.top_topics,
                "important_questions": activity.important_questions,
                "unanswered_questions": activity.unanswered_questions,
                "repeated_questions": activity.repeated_questions,
                "moderation_highlights": moderation_events or activity.moderation_highlights,
            },
            "response_shape": {
                "overview": "string",
                "top_topics": ["string"],
                "important_questions": ["string"],
                "unanswered_questions": ["string"],
                "moderation_highlights": ["string"],
                "recommendations": ["string"],
                "summary_text": "string",
            },
        }
        if self.provider_name == "openai":
            payload = {
                "model": self.model,
                "input": [
                    {
                        "role": "system",
                        "content": "Return strict JSON for a Telegram admin daily summary. Keep it concise and factual.",
                    },
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
                "text": {"format": {"type": "json_object"}},
            }
            headers = {"Authorization": f"Bearer {self.api_key}"}
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post("https://api.openai.com/v1/responses", headers=headers, json=payload)
            if response.status_code >= 400:
                raise AIProviderError(f"openai_http_{response.status_code}")
            data = response.json()
            content = (((data.get("output") or [{}])[0]).get("content") or [{}])[0]
            parsed = content.get("parsed") or content.get("text") or "{}"
        elif self.provider_name == "gemini":
            payload = {
                "contents": [{"parts": [{"text": json.dumps(prompt, ensure_ascii=False)}]}],
                "generationConfig": {"response_mime_type": "application/json"},
            }
            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{self.model}:generateContent?key={self.api_key}"
            )
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(url, json=payload)
            if response.status_code >= 400:
                raise AIProviderError(f"gemini_http_{response.status_code}")
            data = response.json()
            parsed = (((data.get("candidates") or [{}])[0]).get("content") or {}).get("parts", [{}])[0].get("text", "{}")
        else:
            raise AIProviderError(f"unsupported_provider_{self.provider_name}")

        if isinstance(parsed, str):
            parsed = json.loads(parsed)

        return DailySummaryResult(
            overview=str(parsed.get("overview") or ""),
            top_topics=[str(item) for item in parsed.get("top_topics") or []],
            important_questions=[str(item) for item in parsed.get("important_questions") or []],
            unanswered_questions=[str(item) for item in parsed.get("unanswered_questions") or []],
            moderation_highlights=[str(item) for item in parsed.get("moderation_highlights") or []],
            recommendations=[str(item) for item in parsed.get("recommendations") or []],
            summary_text=str(parsed.get("summary_text") or ""),
        )


async def generate_with_fallback(
    *,
    primary: SummaryGenerator,
    fallback: SummaryGenerator,
    group: Group,
    settings: GroupSummarySettings,
    activity: DailyActivityReport,
) -> DailySummaryResult:
    try:
        return await primary.generate_daily_summary(group, settings, activity, moderation_events=activity.moderation_highlights)
    except Exception as exc:
        logger.warning("daily_summary_llm_failed group_id=%s error=%s", group.id, exc)
        return await fallback.generate_daily_summary(group, settings, activity, moderation_events=activity.moderation_highlights)


def build_summary_generator() -> SummaryGenerator:
    settings = get_settings()
    if settings.ai_provider == "openai" and settings.openai_api_key:
        return LLMSummaryGenerator(provider_name="openai", api_key=settings.openai_api_key, model=settings.openai_model)
    if settings.ai_provider == "gemini" and settings.gemini_api_key:
        return LLMSummaryGenerator(provider_name="gemini", api_key=settings.gemini_api_key, model=settings.gemini_model)
    return DeterministicSummaryGenerator()
