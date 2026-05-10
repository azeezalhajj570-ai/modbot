from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Iterable
from urllib.parse import urlparse
import re

from aiogram.types import Message
from sqlalchemy import Select, and_, distinct, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Group, GroupAdminRole, GroupMessageActivity, ModerationLog, User
from bot.summaries.schemas import ActivityMessageSample, DailyActivityReport

_PREVIEW_LIMIT = 300
_LINK_RE = re.compile(r"(?:https?://|www\.|t\.me/)[^\s]+", re.IGNORECASE)
_LATIN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_ARABIC_RE = re.compile(r"[\u0600-\u06ff]+")
_SPACE_RE = re.compile(r"\s+")
_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how", "i", "in", "is", "it", "of",
    "on", "or", "that", "the", "this", "to", "what", "when", "where", "why", "with", "you", "your",
    "الى", "الى", "التي", "الذي", "الذين", "اليوم", "الى", "اذا", "الى", "في", "من", "على", "عن", "ما", "متى",
    "كيف", "هل", "كم", "لم", "لن", "له", "لها", "هناك", "هذا", "هذه", "ذلك", "ثم", "او", "أو", "انا", "نحن",
}
_QUESTION_WORDS = (
    "how", "when", "where", "why", "what", "can", "does", "could", "is", "are",
    "كيف", "متى", "أين", "اين", "لماذا", "هل", "كم", "ما",
)
_SUSPICIOUS_ACTION_TERMS = ("spam", "scam", "ad")


def truncate_preview(text: str | None, *, limit: int = _PREVIEW_LIMIT) -> str:
    normalized = str(text or "").strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def normalize_text(text: str | None) -> str:
    lowered = str(text or "").strip().lower()
    lowered = _LINK_RE.sub(" ", lowered)
    lowered = re.sub(r"[^\w\s\u0600-\u06ff]", " ", lowered)
    lowered = _SPACE_RE.sub(" ", lowered)
    return lowered.strip()


def is_question_text(text: str | None) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    lowered = value.lower()
    if lowered.endswith("?") or lowered.endswith("؟"):
        return True
    return any(lowered.startswith(f"{word} ") or f" {word} " in lowered for word in _QUESTION_WORDS)


def extract_link_domains(text: str | None) -> list[str]:
    domains: list[str] = []
    for match in _LINK_RE.findall(str(text or "")):
        candidate = match if match.startswith(("http://", "https://")) else f"https://{match}"
        domain = urlparse(candidate).netloc.lower().removeprefix("www.")
        if domain and domain not in domains:
            domains.append(domain)
    return domains


def keyword_tokens(text: str | None) -> list[str]:
    normalized = normalize_text(text)
    tokens = _LATIN_RE.findall(normalized) + _ARABIC_RE.findall(normalized)
    return [token for token in tokens if len(token) > 1 and token not in _STOP_WORDS]


def _topic_candidates(messages: Iterable[ActivityMessageSample]) -> list[str]:
    unigram_counts: Counter[str] = Counter()
    phrase_counts: Counter[str] = Counter()
    for message in messages:
        tokens = keyword_tokens(message.text_preview)
        unigram_counts.update(tokens)
        for index in range(len(tokens) - 1):
            left, right = tokens[index], tokens[index + 1]
            if left == right:
                continue
            phrase_counts.update([f"{left} {right}"])

    topics: list[str] = []
    for phrase, count in phrase_counts.most_common(8):
        if count < 2:
            continue
        topics.append(phrase)
        if len(topics) == 4:
            return topics

    for token, count in unigram_counts.most_common(12):
        if count < 2:
            continue
        topics.append(token.upper() if token.isupper() or token in {"btc", "eth"} else token)
        if len(topics) == 4:
            break
    return topics


def _question_lists(messages: list[ActivityMessageSample], admin_user_ids: set[int]) -> tuple[list[str], list[str], list[str]]:
    question_counts: Counter[str] = Counter()
    first_seen_text: dict[str, str] = {}
    unanswered: list[str] = []
    answered_keys: set[str] = set()

    for index, message in enumerate(messages):
        if not message.is_question or not message.normalized_text:
            continue
        key = message.normalized_text
        question_counts.update([key])
        first_seen_text.setdefault(key, message.text_preview)
        if message.user_id in admin_user_ids:
            answered_keys.add(key)
            continue

        question_tokens = set(keyword_tokens(message.text_preview))
        later_messages = messages[index + 1 :]
        resolved = False
        for later_message in later_messages:
            if later_message.user_id not in admin_user_ids:
                continue
            overlap = question_tokens & set(keyword_tokens(later_message.text_preview))
            if overlap:
                resolved = True
                break
        if not resolved and key not in unanswered:
            unanswered.append(key)

    important_questions = [first_seen_text[key] for key, _count in question_counts.most_common(5)]
    repeated_questions = [first_seen_text[key] for key, count in question_counts.most_common(5) if count > 1]
    unanswered_questions = [first_seen_text[key] for key in unanswered[:5]]
    return important_questions, unanswered_questions, repeated_questions


def _build_recommendations(report: DailyActivityReport) -> list[str]:
    recommendations: list[str] = []
    if report.unanswered_questions:
        recommendations.append("Review unanswered questions and add a pinned FAQ or direct reply.")
    if report.suspicious_messages_count:
        recommendations.append(f"Review {report.suspicious_messages_count} suspicious or spam-related incidents.")
    if report.repeated_questions:
        recommendations.append("Document repeated questions in a reusable admin answer or pinned post.")
    if report.links_count >= 10:
        recommendations.append("Check frequently shared links and pin the trusted resources.")
    return recommendations[:4]


async def record_group_message_activity(
    session: AsyncSession,
    *,
    group: Group,
    message: Message,
) -> None:
    text = str(message.text or message.caption or "")
    domains = extract_link_domains(text)
    payload = {
        "group_id": group.id,
        "message_id": int(message.message_id),
        "user_id": int(message.from_user.id) if message.from_user else None,
        "username": getattr(message.from_user, "username", None),
        "text_preview": truncate_preview(text) or None,
        "normalized_text": truncate_preview(normalize_text(text)) or None,
        "has_link": bool(domains),
        "link_domains": domains,
        "is_question": is_question_text(text),
        "is_forwarded": bool(getattr(message, "forward_date", None) or getattr(message, "forward_origin", None)),
        "reply_to_message_id": getattr(getattr(message, "reply_to_message", None), "message_id", None),
        "created_at": datetime.utcnow(),
    }
    bind = getattr(session, "bind", None) or getattr(getattr(session, "_session", None), "bind", None)
    dialect_name = bind.dialect.name if bind is not None else "sqlite"
    insert_builder = pg_insert if dialect_name == "postgresql" else sqlite_insert
    stmt = insert_builder(GroupMessageActivity.__table__).values(payload)
    await session.execute(
        stmt.on_conflict_do_nothing(index_elements=[GroupMessageActivity.group_id, GroupMessageActivity.message_id])
    )


async def collect_group_activity(
    session: AsyncSession,
    *,
    group_id: int,
    start_at: datetime,
    end_at: datetime,
    max_message_samples: int,
) -> DailyActivityReport:
    time_filter = and_(GroupMessageActivity.group_id == group_id, GroupMessageActivity.created_at >= start_at, GroupMessageActivity.created_at < end_at)

    total_messages = int((await session.execute(select(func.count(GroupMessageActivity.id)).where(time_filter))).scalar_one() or 0)
    active_users_count = int((await session.execute(select(func.count(distinct(GroupMessageActivity.user_id))).where(time_filter, GroupMessageActivity.user_id.is_not(None)))).scalar_one() or 0)
    links_count = int((await session.execute(select(func.count(GroupMessageActivity.id)).where(time_filter, GroupMessageActivity.has_link.is_(True)))).scalar_one() or 0)

    top_user_rows = (
        await session.execute(
            select(
                GroupMessageActivity.user_id,
                func.max(GroupMessageActivity.username).label("username"),
                func.count(GroupMessageActivity.id).label("message_count"),
            )
            .where(time_filter, GroupMessageActivity.user_id.is_not(None))
            .group_by(GroupMessageActivity.user_id)
            .order_by(func.count(GroupMessageActivity.id).desc(), GroupMessageActivity.user_id.asc())
            .limit(5)
        )
    ).all()
    top_users = [
        {"user_id": int(row.user_id), "username": row.username, "message_count": int(row.message_count)}
        for row in top_user_rows
        if row.user_id is not None
    ]

    sample_rows = (
        await session.execute(
            select(GroupMessageActivity)
            .where(time_filter)
            .order_by(GroupMessageActivity.created_at.asc(), GroupMessageActivity.id.asc())
            .limit(max_message_samples)
        )
    ).scalars().all()
    messages = [
        ActivityMessageSample(
            message_id=int(row.message_id),
            user_id=int(row.user_id) if row.user_id is not None else None,
            username=row.username,
            text_preview=row.text_preview or "",
            normalized_text=row.normalized_text or "",
            has_link=bool(row.has_link),
            link_domains=[str(item) for item in row.link_domains or []],
            is_question=bool(row.is_question),
            is_forwarded=bool(row.is_forwarded),
            reply_to_message_id=int(row.reply_to_message_id) if row.reply_to_message_id is not None else None,
            created_at=row.created_at,
        )
        for row in sample_rows
    ]

    admin_ids = set((await session.execute(select(GroupAdminRole.user_id).where(GroupAdminRole.group_id == group_id))).scalars().all())
    owner_tg_id = (
        await session.execute(
            select(User.tg_user_id)
            .join(Group, Group.owner_user_id == User.id)
            .where(Group.id == group_id)
        )
    ).scalar_one_or_none()
    if owner_tg_id is not None:
        admin_ids.add(int(owner_tg_id))

    important_questions, unanswered_questions, repeated_questions = _question_lists(messages, admin_ids)

    moderation_rows = (
        await session.execute(
            select(ModerationLog.action, ModerationLog.reason, func.count(ModerationLog.id).label("count"))
            .where(ModerationLog.group_id == group_id, ModerationLog.created_at >= start_at, ModerationLog.created_at < end_at)
            .group_by(ModerationLog.action, ModerationLog.reason)
            .order_by(func.count(ModerationLog.id).desc(), ModerationLog.action.asc())
        )
    ).all()
    suspicious_messages_count = sum(
        int(row.count)
        for row in moderation_rows
        if any(term in str(row.action).lower() for term in _SUSPICIOUS_ACTION_TERMS)
    )
    deleted_messages_count = sum(int(row.count) for row in moderation_rows if str(row.action).lower().startswith("delete_"))
    moderation_highlights = [
        f"{row.action.replace('_', ' ')}: {int(row.count)}"
        if not row.reason
        else f"{row.action.replace('_', ' ')} ({row.reason}): {int(row.count)}"
        for row in moderation_rows[:5]
    ]

    domains_counter: Counter[str] = Counter()
    links: list[dict[str, object]] = []
    for message in messages:
        if not message.has_link:
            continue
        for domain in message.link_domains:
            domains_counter.update([domain])
        links.append({"preview": message.text_preview, "domains": message.link_domains})

    report = DailyActivityReport(
        total_messages=total_messages,
        active_users_count=active_users_count,
        links_count=links_count,
        suspicious_messages_count=suspicious_messages_count,
        deleted_messages_count=deleted_messages_count,
        top_users=top_users,
        top_topics=_topic_candidates(messages),
        important_questions=important_questions,
        unanswered_questions=unanswered_questions,
        repeated_questions=repeated_questions,
        links=links[:10],
        moderation_highlights=moderation_highlights,
        message_samples=messages,
    )
    return report
