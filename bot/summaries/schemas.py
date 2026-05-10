from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ActivityMessageSample:
    message_id: int
    user_id: int | None
    username: str | None
    text_preview: str
    normalized_text: str
    has_link: bool
    link_domains: list[str]
    is_question: bool
    is_forwarded: bool
    reply_to_message_id: int | None
    created_at: datetime


@dataclass
class DailyActivityReport:
    total_messages: int
    active_users_count: int
    links_count: int
    suspicious_messages_count: int
    deleted_messages_count: int
    top_users: list[dict[str, object]] = field(default_factory=list)
    top_topics: list[str] = field(default_factory=list)
    important_questions: list[str] = field(default_factory=list)
    unanswered_questions: list[str] = field(default_factory=list)
    repeated_questions: list[str] = field(default_factory=list)
    links: list[dict[str, object]] = field(default_factory=list)
    moderation_highlights: list[str] = field(default_factory=list)
    message_samples: list[ActivityMessageSample] = field(default_factory=list)


@dataclass
class DailySummaryResult:
    overview: str
    top_topics: list[str]
    important_questions: list[str]
    unanswered_questions: list[str]
    moderation_highlights: list[str]
    recommendations: list[str]
    summary_text: str
