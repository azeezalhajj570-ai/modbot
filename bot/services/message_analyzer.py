"""AI-powered message analysis: extract FAQ from scraped group messages."""
from __future__ import annotations

import json
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import get_settings
from bot.db.models import FAQEntry, FAQSourceType, Group, ScrapedGroup, ScrapedMessage

CHUNK_SIZE = 200

SYSTEM_PROMPT = (
    "You are an FAQ extraction expert. Analyze these Telegram group messages and extract "
    "common questions and their answers. Focus on:\n"
    "- Frequently asked questions\n"
    "- Questions that received detailed answers\n"
    "- Recurring topics discussed in the group\n"
    "- Support/help questions and resolutions\n\n"
    "Return a JSON list of FAQ entries: [{\"question\": \"...\", \"answer\": \"...\", "
    "\"keywords\": [\"kw1\", \"kw2\"], \"category\": \"general\"}]\n"
    "Only include entries where a clear question AND answer can be extracted. "
    "Keep answers concise (max 500 chars). Do not include entries without clear answers."
)


async def _call_openai(messages_text: str, settings: Any) -> list[dict]:
    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
    payload = {
        "model": settings.openai_model,
        "input": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Analyze these group messages for FAQ extraction:\n\n{messages_text}"},
        ],
        "text": {"format": {"type": "json_object"}},
    }
    async with httpx.AsyncClient(timeout=settings.ai_request_timeout_seconds) as client:
        resp = await client.post("https://api.openai.com/v1/responses", headers=headers, json=payload)
    if resp.status_code >= 400:
        raise RuntimeError(f"openai_error_{resp.status_code}")
    data = resp.json()
    output = data.get("output", [])
    if not output:
        raise RuntimeError("openai_empty_output")
    content = output[0].get("content", [])
    if not content:
        raise RuntimeError("openai_missing_content")
    parsed = content[0].get("parsed") or content[0].get("text") or "[]"
    if isinstance(parsed, str):
        parsed = json.loads(parsed)
    if isinstance(parsed, dict):
        for k in ("entries", "faq", "results", "questions", "items"):
            if k in parsed:
                parsed = parsed[k]
                break
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        raise RuntimeError("unexpected_response_format")
    return parsed


async def _call_gemini(messages_text: str, settings: Any) -> list[dict]:
    prompt = SYSTEM_PROMPT + f"\n\nMessages to analyze:\n\n{messages_text}"
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.gemini_model}:generateContent?key={settings.gemini_api_key}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"response_mime_type": "application/json"},
    }
    async with httpx.AsyncClient(timeout=settings.ai_request_timeout_seconds) as client:
        resp = await client.post(url, json=payload)
    if resp.status_code >= 400:
        raise RuntimeError(f"gemini_error_{resp.status_code}")
    data = resp.json()
    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError("gemini_empty_output")
    text_out = candidates[0]["content"]["parts"][0].get("text", "[]")
    parsed = json.loads(text_out)
    if isinstance(parsed, dict):
        for k in ("entries", "faq", "results", "questions", "items"):
            if k in parsed:
                parsed = parsed[k]
                break
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        raise RuntimeError("unexpected_response_format")
    return parsed


async def _call_openrouter(messages_text: str, settings: Any) -> list[dict]:
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
    }
    if settings.openrouter_app_url:
        headers["HTTP-Referer"] = settings.openrouter_app_url
    headers["X-Title"] = settings.openrouter_app_title
    payload = {
        "model": settings.openrouter_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Analyze these group messages for FAQ extraction. Return only valid JSON:\n\n{messages_text}"},
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient(timeout=settings.ai_request_timeout_seconds) as client:
        resp = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"openrouter_error_{resp.status_code}")
    data = resp.json()
    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError("openrouter_empty_output")
    content = choices[0].get("message", {}).get("content", "[]")
    parsed = json.loads(content)
    if isinstance(parsed, dict):
        for k in ("entries", "faq", "results", "questions", "items"):
            if k in parsed:
                parsed = parsed[k]
                break
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        raise RuntimeError("unexpected_response_format")
    return parsed


def _chunk_messages(messages: list[ScrapedMessage]) -> list[str]:
    chunks = []
    current = ""
    for msg in messages:
        text = (msg.message_text or "").strip()
        if not text or len(text) < 10:
            continue
        line = f"[{msg.message_id}] {text}\n"
        if len(current) + len(line) > 8000:
            chunks.append(current)
            current = line
        else:
            current += line
    if current:
        chunks.append(current)
    return chunks


async def analyze_group_messages(
    session: AsyncSession,
    *,
    tg_group_id: int,
    max_messages: int = 1000,
) -> dict[str, Any]:
    """Analyze scraped messages from a group and generate FAQ entries."""
    settings = get_settings()
    provider = settings.ai_provider.lower()

    if provider not in ("openai", "gemini", "openrouter"):
        return {"error": "AI provider not configured. Set AI_PROVIDER to openai, gemini, or openrouter."}

    if provider == "openai" and not settings.openai_api_key:
        return {"error": "OPENAI_API_KEY not configured."}
    if provider == "gemini" and not settings.gemini_api_key:
        return {"error": "GEMINI_API_KEY not configured."}
    if provider == "openrouter" and not settings.openrouter_api_key:
        return {"error": "OPENROUTER_API_KEY not configured."}

    group = (await session.execute(
        select(ScrapedGroup).where(ScrapedGroup.tg_group_id == tg_group_id)
    )).scalar_one_or_none()

    if group is None:
        return {"error": f"No scraped group found for tg_group_id={tg_group_id}"}

    managed_group = (await session.execute(
        select(Group).where(Group.tg_group_id == tg_group_id)
    )).scalar_one_or_none()

    managed_group_id = managed_group.id if managed_group else None

    messages = (await session.execute(
        select(ScrapedMessage)
        .where(
            ScrapedMessage.tg_group_id == tg_group_id,
            ScrapedMessage.message_text.is_not(None),
        )
        .order_by(ScrapedMessage.message_date.desc())
        .limit(max_messages)
    )).scalars().all()

    if not messages:
        return {"error": "No messages found for analysis. Scrape the group first."}

    chunks = _chunk_messages(messages)
    if not chunks:
        return {"error": "No message text content found for analysis."}

    all_entries = []
    errors = []
    for i, chunk in enumerate(chunks):
        try:
            if provider == "openai":
                entries = await _call_openai(chunk, settings)
            elif provider == "openrouter":
                entries = await _call_openrouter(chunk, settings)
            else:
                entries = await _call_gemini(chunk, settings)
            all_entries.extend(entries)
        except Exception as exc:
            errors.append(f"chunk_{i}: {str(exc)}")

    seen = set()
    saved_count = 0
    for entry in all_entries:
        question = str(entry.get("question") or "").strip()
        answer = str(entry.get("answer") or "").strip()[:2000]
        if not question or not answer or len(question) < 5:
            continue
        q_lower = question.lower()
        if q_lower in seen:
            continue
        seen.add(q_lower)

        keywords = entry.get("keywords", [])
        if isinstance(keywords, str):
            keywords = [k.strip() for k in keywords.split(",") if k.strip()]

        existing = (await session.execute(
            select(FAQEntry).where(
                FAQEntry.group_id == managed_group_id,
                FAQEntry.question.ilike(f"%{question[:30]}%"),
            )
        )).scalar_one_or_none() if managed_group_id else None
        if existing:
            continue

        session.add(FAQEntry(
            group_id=managed_group_id or 0,
            question=question,
            answer=answer,
            keywords=keywords,
            category=str(entry.get("category") or "general")[:50],
            source_type=FAQSourceType.IMPORTED,
            enabled=True,
        ))
        saved_count += 1

    await session.commit()

    return {
        "messages_analyzed": len(messages),
        "chunks_processed": len(chunks),
        "entries_extracted": len(all_entries),
        "entries_saved": saved_count,
        "errors": errors,
    }
