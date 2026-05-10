from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from bot.db.base import Base
from bot.db.models import DailyGroupSummary, Group, GroupAdminRole, GroupMessageActivity, GroupSummarySettings, ModerationLog, User
from bot.summaries.collector import collect_group_activity, extract_link_domains, is_question_text, record_group_message_activity
from bot.summaries.generator import DeterministicSummaryGenerator
from bot.summaries.service import DailyAdminSummaryService


class AsyncSessionAdapter:
    def __init__(self, session) -> None:
        self._session = session

    async def execute(self, stmt):
        return self._session.execute(stmt)

    def add(self, instance) -> None:
        self._session.add(instance)

    def add_all(self, instances) -> None:
        self._session.add_all(instances)

    async def flush(self) -> None:
        self._session.flush()

    async def commit(self) -> None:
        self._session.commit()

    async def rollback(self) -> None:
        self._session.rollback()

    async def refresh(self, instance) -> None:
        self._session.refresh(instance)


class SessionContextFactory:
    def __init__(self, maker) -> None:
        self._maker = maker

    def __call__(self):
        factory = self

        class _Ctx:
            async def __aenter__(self):
                self._sync_session = factory._maker()
                self._adapter = AsyncSessionAdapter(self._sync_session)
                return self._adapter

            async def __aexit__(self, _exc_type, _exc, _tb) -> None:
                self._sync_session.close()

        return _Ctx()


@pytest.fixture
def sync_engine(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'summary.sqlite3'}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            Group.__table__,
            GroupAdminRole.__table__,
            GroupSummarySettings.__table__,
            DailyGroupSummary.__table__,
            GroupMessageActivity.__table__,
            ModerationLog.__table__,
        ],
    )
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def sync_session_maker(sync_engine):
    return sessionmaker(bind=sync_engine, expire_on_commit=False, autoflush=False)


@pytest_asyncio.fixture
async def db_session(sync_session_maker):
    session = sync_session_maker()
    adapter = AsyncSessionAdapter(session)
    try:
        yield adapter
    finally:
        session.close()


@pytest.fixture
def session_factory(sync_session_maker):
    return SessionContextFactory(sync_session_maker)


async def _seed_group(db_session, *, tg_group_id: int = -100991) -> Group:
    owner = User(tg_user_id=7001, username="owner", full_name="Owner", language_code="en")
    db_session.add(owner)
    await db_session.flush()
    group = Group(tg_group_id=tg_group_id, title="Summary Group", owner_user_id=owner.id, is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=owner.tg_user_id, role="owner"))
    await db_session.commit()
    return group


@pytest.mark.asyncio
async def test_summary_settings_defaults(db_session) -> None:
    group = await _seed_group(db_session)
    settings = GroupSummarySettings(group_id=group.id)
    db_session.add(settings)
    await db_session.commit()
    await db_session.refresh(settings)

    assert settings.enabled is False
    assert settings.timezone == "Asia/Aden"
    assert settings.summary_time == "21:00"
    assert settings.delivery_mode == "dashboard_only"


@pytest.mark.asyncio
async def test_message_collection_counts(db_session) -> None:
    group = await _seed_group(db_session, tg_group_id=-100992)
    now = datetime.utcnow()
    db_session.add_all(
        [
            GroupMessageActivity(group_id=group.id, message_id=1, user_id=1, username="alice", text_preview="BTC now", normalized_text="btc now", created_at=now),
            GroupMessageActivity(group_id=group.id, message_id=2, user_id=2, username="bob", text_preview="See https://example.com", normalized_text="see", has_link=True, link_domains=["example.com"], created_at=now + timedelta(minutes=1)),
            GroupMessageActivity(group_id=group.id, message_id=3, user_id=1, username="alice", text_preview="Binance update", normalized_text="binance update", created_at=now + timedelta(minutes=2)),
        ]
    )
    await db_session.commit()

    report = await collect_group_activity(
        db_session,
        group_id=group.id,
        start_at=now - timedelta(minutes=1),
        end_at=now + timedelta(days=1),
        max_message_samples=100,
    )

    assert report.total_messages == 3
    assert report.active_users_count == 2
    assert report.links_count == 1


@pytest.mark.asyncio
async def test_question_detection_arabic() -> None:
    assert is_question_text("متى يبدأ الدرس اليوم؟") is True


@pytest.mark.asyncio
async def test_question_detection_english() -> None:
    assert is_question_text("When does the session start?") is True


@pytest.mark.asyncio
async def test_link_extraction() -> None:
    domains = extract_link_domains("Join here https://example.com/course")
    assert domains == ["example.com"]


@pytest.mark.asyncio
async def test_top_users_sorted_by_count(db_session) -> None:
    group = await _seed_group(db_session, tg_group_id=-100993)
    now = datetime.utcnow()
    rows = [
        GroupMessageActivity(group_id=group.id, message_id=1, user_id=10, username="alice", text_preview="a", normalized_text="a", created_at=now),
        GroupMessageActivity(group_id=group.id, message_id=2, user_id=10, username="alice", text_preview="b", normalized_text="b", created_at=now),
        GroupMessageActivity(group_id=group.id, message_id=3, user_id=11, username="bob", text_preview="c", normalized_text="c", created_at=now),
    ]
    db_session.add_all(rows)
    await db_session.commit()

    report = await collect_group_activity(db_session, group_id=group.id, start_at=now - timedelta(days=1), end_at=now + timedelta(days=1), max_message_samples=100)
    assert [user["user_id"] for user in report.top_users] == [10, 11]


@pytest.mark.asyncio
async def test_top_topics_include_relevant_keywords(db_session) -> None:
    group = await _seed_group(db_session, tg_group_id=-100994)
    now = datetime.utcnow()
    texts = [
        "BTC price movement today",
        "Binance verification issue",
        "BTC trading setup",
        "Trading signal for BTC",
    ]
    for index, text in enumerate(texts, start=1):
        db_session.add(
            GroupMessageActivity(
                group_id=group.id,
                message_id=index,
                user_id=index,
                username=f"u{index}",
                text_preview=text,
                normalized_text=text.lower(),
                created_at=now + timedelta(minutes=index),
            )
        )
    await db_session.commit()

    report = await collect_group_activity(db_session, group_id=group.id, start_at=now - timedelta(days=1), end_at=now + timedelta(days=1), max_message_samples=100)
    lowered = " ".join(report.top_topics).lower()
    assert "btc" in lowered
    assert "trading" in lowered or "binance" in lowered


@pytest.mark.asyncio
async def test_unanswered_questions_detected(db_session) -> None:
    group = await _seed_group(db_session, tg_group_id=-100995)
    now = datetime.utcnow()
    db_session.add_all(
        [
            GroupMessageActivity(group_id=group.id, message_id=1, user_id=300, username="member", text_preview="Is today's Zoom link changed?", normalized_text="is today s zoom link changed", is_question=True, created_at=now),
            GroupMessageActivity(group_id=group.id, message_id=2, user_id=301, username="member2", text_preview="Random follow up", normalized_text="random follow up", created_at=now + timedelta(minutes=2)),
        ]
    )
    await db_session.commit()

    report = await collect_group_activity(db_session, group_id=group.id, start_at=now - timedelta(days=1), end_at=now + timedelta(days=1), max_message_samples=100)
    assert "Zoom link" in report.unanswered_questions[0]


@pytest.mark.asyncio
async def test_moderation_events_included(db_session) -> None:
    group = await _seed_group(db_session, tg_group_id=-100996)
    now = datetime.utcnow()
    db_session.add(GroupMessageActivity(group_id=group.id, message_id=1, user_id=1, username="alice", text_preview="test", normalized_text="test", created_at=now))
    db_session.add_all(
        [
            ModerationLog(group_id=group.id, action="delete_spam", target_user_id=12, admin_user_id=7001, reason="spam", details={}, created_at=now),
            ModerationLog(group_id=group.id, action="warn_spam", target_user_id=12, admin_user_id=7001, reason="spam", details={}, created_at=now),
        ]
    )
    await db_session.commit()

    report = await collect_group_activity(db_session, group_id=group.id, start_at=now - timedelta(days=1), end_at=now + timedelta(days=1), max_message_samples=100)
    result = await DeterministicSummaryGenerator().generate_daily_summary(group, GroupSummarySettings(group_id=group.id), report)
    assert report.suspicious_messages_count == 2
    assert report.deleted_messages_count == 1
    assert any("delete spam" in item for item in result.moderation_highlights)


@pytest.mark.asyncio
async def test_summary_idempotency(db_session) -> None:
    group = await _seed_group(db_session, tg_group_id=-100997)
    service = DailyAdminSummaryService(db_session, bot=None)

    first = await service.generate_summary_for_group(group.id, date(2026, 4, 26), deliver=False)
    second = await service.generate_summary_for_group(group.id, date(2026, 4, 26), deliver=False)

    rows = (await db_session.execute(select(DailyGroupSummary).where(DailyGroupSummary.group_id == group.id))).scalars().all()
    assert first.id == second.id
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_fallback_behavior_when_generator_fails(db_session) -> None:
    class FailingGenerator:
        async def generate_daily_summary(self, *args, **kwargs):
            raise RuntimeError("llm failed")

    group = await _seed_group(db_session, tg_group_id=-100998)
    service = DailyAdminSummaryService(db_session, bot=None, generator=FailingGenerator())

    summary = await service.generate_summary_for_group(group.id, date(2026, 4, 26), deliver=False)
    assert summary.summary_text.startswith("Daily Summary")
    assert summary.status == "generated"


@pytest.mark.asyncio
async def test_record_group_message_activity_uses_preview_only(db_session) -> None:
    group = await _seed_group(db_session, tg_group_id=-100999)
    long_text = "x" * 500
    message = SimpleNamespace(
        text=long_text,
        caption=None,
        message_id=900,
        from_user=SimpleNamespace(id=55, username="tester"),
        forward_date=None,
        forward_origin=None,
        reply_to_message=None,
    )

    await record_group_message_activity(db_session, group=group, message=message)
    await db_session.commit()

    activity = (await db_session.execute(select(GroupMessageActivity).where(GroupMessageActivity.group_id == group.id))).scalar_one()
    assert len(activity.text_preview) == 300
