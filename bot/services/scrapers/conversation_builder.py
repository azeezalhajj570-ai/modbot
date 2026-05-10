"""Build conversation threads from scraped messages."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import ScrapedConversation
from bot.services.group_service import canonical_tg_group_id

logger = structlog.get_logger(__name__)

CONVERSATION_IDLE_MINUTES = 30


async def build_conversations_from_scrape(
    session: AsyncSession,
    *,
    scraped_group_id: int,
    tg_group_id: int,
    message_rows: list[dict[str, Any]],
) -> int:
    canonical_id = canonical_tg_group_id(int(tg_group_id))
    thread_map: dict[int, list[dict[str, Any]]] = defaultdict(list)
    root_map: dict[int, dict[str, Any]] = {}
    standalone: list[dict[str, Any]] = []

    for row in message_rows:
        reply_to = row.get("reply_to_message_id")
        reply_top = row.get("reply_to_top_id")
        key = reply_top or reply_to or 0
        if key:
            thread_map[key].append(row)
            if key not in root_map:
                root_map[key] = row
        else:
            standalone.append(row)

    created = 0
    for root_id, messages in thread_map.items():
        root_msg = root_map[root_id]
        participants = set()
        for m in messages:
            uid = m.get("sender_user_id")
            if uid:
                participants.add(int(uid))
        first_date = root_msg.get("message_date")
        last_date = max(
            (m.get("message_date") for m in messages if m.get("message_date")),
            default=first_date,
        )
        title = (root_msg.get("message_text") or "")[:200]
        if not title:
            title = f"Conversation #{root_id}"

        conv_result = (
            await session.execute(
                select(ScrapedConversation).where(
                    ScrapedConversation.scraped_group_id == scraped_group_id,
                    ScrapedConversation.root_message_id == int(root_id),
                ).order_by(ScrapedConversation.id.desc()).limit(1)
            )
        )
        conv = conv_result.scalars().first()

        sender_name = root_msg.get("sender_first_name") or root_msg.get("sender_username") or ""
        if conv is None:
            session.add(ScrapedConversation(
                scraped_group_id=scraped_group_id,
                tg_group_id=canonical_id,
                root_message_id=int(root_id),
                root_message_text=root_msg.get("message_text"),
                root_sender_user_id=root_msg.get("sender_user_id"),
                root_sender_name=sender_name,
                title=title,
                participant_count=len(participants),
                message_count=len(messages),
                first_message_at=first_date,
                last_message_at=last_date,
                is_topic=bool(root_msg.get("reply_to_top_id")),
            ))
            created += 1
        else:
            conv.message_count = len(messages)
            conv.participant_count = len(participants)
            conv.last_message_at = last_date
            if sender_name and not conv.root_sender_name:
                conv.root_sender_name = sender_name
            if not conv.title or conv.title.startswith("Conversation #"):
                conv.title = title

    if standalone:
        standalone.sort(key=lambda m: m.get("message_date") or datetime.min)
        current_group: list[dict[str, Any]] = []
        for msg in standalone:
            if not current_group:
                current_group.append(msg)
            else:
                last = current_group[-1]
                last_date = last.get("message_date")
                curr_date = msg.get("message_date")
                same_sender = last.get("sender_user_id") == msg.get("sender_user_id") and msg.get("sender_user_id") is not None
                if curr_date and last_date and (curr_date - last_date) <= timedelta(minutes=CONVERSATION_IDLE_MINUTES) and same_sender:
                    current_group.append(msg)
                else:
                    created += await _save_time_group(session, scraped_group_id, canonical_id, current_group)
                    current_group = [msg]
        if current_group:
            created += await _save_time_group(session, scraped_group_id, canonical_id, current_group)

    await session.commit()
    return created


async def _save_time_group(
    session: AsyncSession,
    scraped_group_id: int,
    tg_group_id: int,
    messages: list[dict[str, Any]],
) -> int:
    if not messages:
        return 0
    first = messages[0]
    participants = set()
    for m in messages:
        uid = m.get("sender_user_id")
        if uid:
            participants.add(int(uid))
    dates = [m.get("message_date") for m in messages if m.get("message_date")]
    title = (first.get("message_text") or "")[:200] or f"Discussion ({len(messages)} messages)"
    session.add(ScrapedConversation(
        scraped_group_id=scraped_group_id,
        tg_group_id=tg_group_id,
        root_message_id=first.get("message_id"),
        root_message_text=first.get("message_text"),
        root_sender_user_id=first.get("sender_user_id"),
        root_sender_name=first.get("sender_first_name") or first.get("sender_username") or "",
        title=title,
        participant_count=len(participants),
        message_count=len(messages),
        first_message_at=min(dates) if dates else None,
        last_message_at=max(dates) if dates else None,
    ))
    return 1
