from __future__ import annotations

from datetime import datetime

import pytest

from bot.db.models import Group, GroupSummarySettings
from bot.summaries.generator import DeterministicSummaryGenerator, generate_with_fallback
from bot.summaries.schemas import ActivityMessageSample, DailyActivityReport, DailySummaryResult


@pytest.mark.asyncio
async def test_deterministic_generator_builds_human_readable_summary() -> None:
    group = Group(id=1, tg_group_id=-1001, title="Arabic Crypto Group", is_active=True)
    settings = GroupSummarySettings(group_id=1)
    report = DailyActivityReport(
        total_messages=1240,
        active_users_count=183,
        links_count=47,
        suspicious_messages_count=19,
        deleted_messages_count=7,
        top_users=[{"user_id": 1, "username": "alice", "message_count": 55}],
        top_topics=["BTC", "binance verification", "trading signals"],
        important_questions=["When is the next trading session?"],
        unanswered_questions=["Is today's Zoom link changed?"],
        moderation_highlights=["delete spam: 12"],
        message_samples=[
            ActivityMessageSample(
                message_id=1,
                user_id=1,
                username="alice",
                text_preview="BTC price movement today",
                normalized_text="btc price movement today",
                has_link=False,
                link_domains=[],
                is_question=False,
                is_forwarded=False,
                reply_to_message_id=None,
                created_at=datetime.utcnow(),
            )
        ],
    )

    result = await DeterministicSummaryGenerator().generate_daily_summary(group, settings, report)

    assert "Daily Summary" in result.summary_text
    assert "BTC" in result.summary_text
    assert result.recommendations


@pytest.mark.asyncio
async def test_generate_with_fallback_uses_deterministic_when_primary_fails() -> None:
    class FailingGenerator:
        async def generate_daily_summary(self, *args, **kwargs):
            raise RuntimeError("boom")

    group = Group(id=2, tg_group_id=-1002, title="Fallback Group", is_active=True)
    settings = GroupSummarySettings(group_id=2)
    report = DailyActivityReport(
        total_messages=5,
        active_users_count=2,
        links_count=0,
        suspicious_messages_count=0,
        deleted_messages_count=0,
    )

    result = await generate_with_fallback(
        primary=FailingGenerator(),
        fallback=DeterministicSummaryGenerator(),
        group=group,
        settings=settings,
        activity=report,
    )

    assert isinstance(result, DailySummaryResult)
    assert result.summary_text.startswith("Daily Summary")
