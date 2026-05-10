from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from bot.db.base import Base
from bot.db.models import DailyGroupSummary, Group, GroupAdminRole, GroupMessageActivity, GroupSummarySettings, ModerationLog, User
from bot.summaries.delivery import send_daily_summary
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

    async def refresh(self, instance) -> None:
        self._session.refresh(instance)

    async def rollback(self) -> None:
        self._session.rollback()


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
        f"sqlite:///{tmp_path / 'summary-delivery.sqlite3'}",
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


async def _seed_group(db_session, *, tg_group_id: int) -> Group:
    owner = User(tg_user_id=8101, username="owner", full_name="Owner", language_code="en")
    db_session.add(owner)
    await db_session.flush()
    group = Group(tg_group_id=tg_group_id, title="Delivery Group", owner_user_id=owner.id, is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=owner.tg_user_id, role="owner"))
    await db_session.commit()
    return group


@pytest.mark.asyncio
async def test_dashboard_only_delivery_does_not_send_message(db_session, fake_bot) -> None:
    group = await _seed_group(db_session, tg_group_id=-100881)
    settings = GroupSummarySettings(group_id=group.id, delivery_mode="dashboard_only")
    summary = DailyGroupSummary(group_id=group.id, summary_date=date(2026, 4, 26), summary_text="hello")

    status = await send_daily_summary(db_session, group=group, summary=summary, settings=settings, bot=fake_bot)

    assert status == "generated"
    assert fake_bot.sent_messages == []


@pytest.mark.asyncio
async def test_admin_dm_delivery_sends_to_admin_chat(db_session, fake_bot) -> None:
    group = await _seed_group(db_session, tg_group_id=-100882)
    settings = GroupSummarySettings(group_id=group.id, delivery_mode="admin_dm", admin_chat_id=998877)
    summary = DailyGroupSummary(group_id=group.id, summary_date=date(2026, 4, 26), summary_text="delivery text")

    status = await send_daily_summary(db_session, group=group, summary=summary, settings=settings, bot=fake_bot)

    assert status == "sent"
    assert fake_bot.sent_messages[0] == (998877, "delivery text")


@pytest.mark.asyncio
async def test_group_message_delivery_requires_explicit_setting(db_session, fake_bot) -> None:
    group = await _seed_group(db_session, tg_group_id=-100883)
    service = DailyAdminSummaryService(db_session, bot=fake_bot)
    await service.update_settings(group.id, {"enabled": True})

    summary = await service.generate_summary_for_group(group.id, date(2026, 4, 26), deliver=True)

    assert summary.status == "generated"
    assert fake_bot.sent_messages == []
