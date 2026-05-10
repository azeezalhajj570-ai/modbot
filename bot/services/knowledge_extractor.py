from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any

import aiohttp
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import get_settings
from bot.db.models import ScrapedDailySummary, ScrapedGroup, ScrapedMessage
from bot.db.models.scraper import GroupKnowledge

logger = logging.getLogger(__name__)

KNOWLEDGE_EXTRACTION_PROMPT = """Analyze these Telegram group messages and extract structured knowledge.
Return a JSON object with these keys:

"faqs": Array of {question, answer, category, keywords[]} for frequently asked questions with clear answers.
"topics": Array of {topic, description, message_count, sentiment (positive/neutral/negative)} for discussion themes.
"entities": Array of {name, type(person/organization/product/link/event), mentions, context} for mentioned things.
"decisions": Array of {decision, rationale, participants[], confidence (0.0-1.0)} for group decisions/consensus.
"trends": Array of {trend, direction(rising/stable/declining), evidence} for observable patterns.
"insights": Array of {insight, importance (low/medium/high), actionable (true/false)} for key takeaways.

Only include items with confidence >= 0.6. Be concise. Focus on actionable knowledge.

Messages:
{chunk_text}"""

DAILY_SUMMARY_PROMPT = """Summarize this day's Telegram group activity into a concise JSON:

{
  "summary": "1-2 paragraph summary of key discussions, decisions, and notable events",
  "top_topics": {"topic_name": message_count, ...},
  "active_users": [user_id1, user_id2, ...],  (most active, top 10)
  "highlights": ["highlight 1", "highlight 2", ...],
  "decisions_made": ["decision 1", "decision 2", ...],
  "sentiment": {"positive": N, "neutral": N, "negative": N}
}

Messages for date {date}:
{messages_text}"""


def _format_prompt(template: str, chunk_text: str, **extra) -> str:
    """Format prompt template safely without interpreting JSON curly braces."""
    result = template.replace("{chunk_text}", chunk_text)
    for key, value in extra.items():
        result = result.replace(f"{{{key}}}", str(value))
    return result


class KnowledgeExtractor:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._settings = get_settings()

    async def extract_knowledge(self, *, scraped_group_id: int, max_messages: int = 2000) -> dict[str, Any]:
        messages = await self._fetch_message_texts(scraped_group_id, max_messages)
        if not messages:
            return {"status": "no_messages"}

        chunks = self._chunk_messages(messages, max_chars=8000)
        all_results: dict[str, list[dict[str, Any]]] = {
            "faqs": [], "topics": [], "entities": [], "decisions": [], "trends": [], "insights": [],
        }
        total_cost = 0.0

        for i, chunk in enumerate(chunks):
            if i > 0:
                await asyncio.sleep(1.5)
            result, cost = await self._call_ai(KNOWLEDGE_EXTRACTION_PROMPT, chunk_text=chunk, phase="bulk")
            total_cost += cost
            if result:
                for key in all_results:
                    items = result.get(key, [])
                    if isinstance(items, list):
                        all_results[key].extend(items)

        refined_results, refine_cost = await self._refine_knowledge(all_results)
        total_cost += refine_cost

        saved_count = await self._save_knowledge(scraped_group_id, refined_results)
        logger.info("knowledge_extraction_done", scraped_group_id=scraped_group_id, saved=saved_count, cost_estimate=round(total_cost, 4))
        return {"items_saved": saved_count, "cost_estimate": round(total_cost, 4)}

    async def generate_daily_summary(self, *, scraped_group_id: int, date: datetime) -> ScrapedDailySummary | None:
        messages = await self._fetch_message_texts(scraped_group_id, 500, date=date)
        if not messages:
            return None

        chunk_text = " ".join(text for _, text in messages)
        if len(chunk_text) < 100:
            return None

        result, cost = await self._call_ai(
            DAILY_SUMMARY_PROMPT,
            chunk_text="",
            messages_text=chunk_text[:12000],
            date=date.strftime("%Y-%m-%d"),
            phase="summary",
        )
        if not result:
            return None

        user_ids = sorted({
            uid for uid, _ in messages if uid is not None
        })[:10]

        summary = ScrapedDailySummary(
            scraped_group_id=scraped_group_id,
            date=date,
            message_count=len(messages),
            active_users=user_ids,
            top_topics=result.get("top_topics"),
            summary=result.get("summary"),
        )
        self.session.add(summary)
        await self.session.commit()
        return summary

    async def _fetch_message_texts(self, scraped_group_id: int, max_messages: int, date: datetime | None = None) -> list[tuple[int | None, str]]:
        stmt = select(ScrapedMessage.sender_user_id, ScrapedMessage.message_text).where(
            ScrapedMessage.scraped_group_id == scraped_group_id,
            ScrapedMessage.message_text.isnot(None),
            func.length(ScrapedMessage.message_text) >= 10,
        )
        if date is not None:
            start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = start_of_day + timedelta(days=1)
            stmt = stmt.where(
                ScrapedMessage.message_date >= start_of_day,
                ScrapedMessage.message_date < end_of_day,
            )
        stmt = stmt.order_by(ScrapedMessage.message_date.desc()).limit(max_messages)
        result = await self.session.execute(stmt)
        return [(row[0], str(row[1])) for row in result.all() if row[1] is not None]

    def _chunk_messages(self, messages: list[tuple[int | None, str]], max_chars: int = 8000) -> list[str]:
        chunks: list[str] = []
        current: list[str] = []
        current_len = 0
        for uid, text in messages:
            prefix = f"[u{uid}] " if uid else ""
            line = prefix + text
            if current_len + len(line) > max_chars and current:
                chunks.append(" ".join(current))
                current = []
                current_len = 0
            current.append(line)
            current_len += len(line)
        if current:
            chunks.append(" ".join(current))
        return chunks

    async def _call_ai(self, prompt_template: str, *, chunk_text: str = "", **extra) -> tuple[dict[str, Any] | None, float]:
        settings = self._settings
        provider = settings.ai_provider

        if provider == "openai":
            return await self._call_openai(prompt_template, chunk_text, **extra)
        elif provider == "gemini":
            return await self._call_gemini(prompt_template, chunk_text, **extra)
        elif provider == "openrouter":
            return await self._call_openrouter(prompt_template, chunk_text, **extra)
        else:
            return None, 0.0

    async def _call_openai(self, prompt_template: str, chunk_text: str, **extra) -> tuple[dict[str, Any] | None, float]:
        api_key = self._settings.openai_api_key
        if not api_key:
            return None, 0.0

        prompt = _format_prompt(prompt_template, chunk_text, **extra)
        payload = {
            "model": self._settings.openai_model,
            "messages": [
                {"role": "system", "content": "You are a knowledge extraction engine. Return only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 2000,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=self._settings.ai_request_timeout_seconds),
                ) as resp:
                    data = await resp.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    usage = data.get("usage", {})
                    cost = (usage.get("prompt_tokens", 0) * 0.00015 + usage.get("completion_tokens", 0) * 0.0006) / 1000
                    return self._parse_json_response(content), cost
        except Exception as exc:
            logger.warning("openai_extract_failed", error=str(exc))
            return None, 0.0

    async def _call_gemini(self, prompt_template: str, chunk_text: str, **extra) -> tuple[dict[str, Any] | None, float]:
        api_key = self._settings.gemini_api_key
        if not api_key:
            return None, 0.0

        prompt = _format_prompt(prompt_template, chunk_text, **extra)
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2000},
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{self._settings.gemini_model}:generateContent",
                    params={"key": api_key},
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=self._settings.ai_request_timeout_seconds),
                ) as resp:
                    data = await resp.json()
                    text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                    usage = data.get("usageMetadata", {})
                    cost = (usage.get("promptTokenCount", 0) * 0.0000375 + usage.get("candidatesTokenCount", 0) * 0.00015) / 1000
                    return self._parse_json_response(text), cost
        except Exception as exc:
            logger.warning("gemini_extract_failed", error=str(exc))
            return None, 0.0

    async def _call_openrouter(self, prompt_template: str, chunk_text: str, phase: str = "bulk", **extra) -> tuple[dict[str, Any] | None, float]:
        api_key = self._settings.openrouter_api_key
        if not api_key:
            return None, 0.0

        if phase == "bulk":
            model = self._settings.openrouter_model_bulk or self._settings.openrouter_model
        elif phase == "premium":
            model = self._settings.openrouter_model_premium or self._settings.openrouter_model
        else:
            model = self._settings.openrouter_model

        prompt = _format_prompt(prompt_template, chunk_text, **extra)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if self._settings.openrouter_app_url:
            headers["HTTP-Referer"] = self._settings.openrouter_app_url
        headers["X-Title"] = self._settings.openrouter_app_title

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a knowledge extraction engine. Return only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 2000,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=self._settings.ai_request_timeout_seconds),
                ) as resp:
                    data = await resp.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    usage = data.get("usage", {})
                    pricing = float(usage.get("prompt_tokens", 0)) * 0.0000001 + float(usage.get("completion_tokens", 0)) * 0.0000004
                    cost = pricing if data.get("total_cost", 0) == 0 else data.get("total_cost", pricing)
                    return self._parse_json_response(content), cost
        except Exception as exc:
            logger.warning("openrouter_extract_failed", error=str(exc))
            return None, 0.0

    async def _refine_knowledge(self, raw_results: dict[str, list[dict[str, Any]]]) -> tuple[dict[str, list[dict[str, Any]]], float]:
        refined: dict[str, list[dict[str, Any]]] = {}
        total_cost = 0.0
        for key, items in raw_results.items():
            if not items:
                refined[key] = []
                continue
            seen = set()
            deduped: list[dict[str, Any]] = []
            for item in items:
                fingerprint = json.dumps(item, sort_keys=True, default=str)
                if fingerprint not in seen:
                    seen.add(fingerprint)
                    conf = item.get("confidence", 0.0)
                    if isinstance(conf, (int, float)) and conf >= 0.5:
                        deduped.append(item)
            refined[key] = deduped
        return refined, total_cost

    async def _save_knowledge(self, scraped_group_id: int, results: dict[str, list[dict[str, Any]]]) -> int:
        saved = 0
        for knowledge_type, items in results.items():
            for item in items:
                entry = GroupKnowledge(
                    scraped_group_id=scraped_group_id,
                    knowledge_type=knowledge_type,
                    title=str(item.get("question") or item.get("topic") or item.get("name") or item.get("decision") or item.get("trend") or item.get("insight", ""))[:500],
                    content=json.dumps(item, default=str),
                    source_message_ids=item.get("source_message_ids"),
                    confidence=float(item.get("confidence", 0.5)),
                    first_seen=datetime.utcnow(),
                    last_updated=datetime.utcnow(),
                )
                self.session.add(entry)
                saved += 1
        if saved:
            await self.session.commit()
        return saved

    @staticmethod
    def _parse_json_response(text: str) -> dict[str, Any] | None:
        if not text:
            return None
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            try:
                start = text.find("{")
                end = text.rfind("}") + 1
                if start >= 0 and end > start:
                    return json.loads(text[start:end])
            except json.JSONDecodeError:
                return None
        return None
