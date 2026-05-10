from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from bot.dashboard.api.main import app
from bot.db.base import Base
from bot.db.models import DailyGroupSummary, Group, GroupAdminRole, GroupMessageActivity, GroupSummarySettings, ModerationLog, User


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
        f"sqlite:///{tmp_path / 'summary-api.sqlite3'}",
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


@pytest_asyncio.fixture
async def api_client(patch_db_dependencies) -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def _webapp_init_data(*, user_id: int, bot_token: str = "123456:TESTTOKEN") -> str:
    payload = {
        "auth_date": str(int(time.time())),
        "query_id": "AAEAAAE",
        "user": json.dumps({"id": user_id, "username": f"user{user_id}", "first_name": "Test"}, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(payload.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    payload["hash"] = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    return urlencode(payload)


@pytest.mark.asyncio
async def test_manual_generate_endpoint_allows_admin(api_client, db_session) -> None:
    group = Group(tg_group_id=-1007711, title="API Summary Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=84520, role="owner"))
    await db_session.commit()

    login = await api_client.post(
        "/api/auth/miniapp/token",
        json={"init_data": _webapp_init_data(user_id=84520)},
        headers={"X-App-Boundary": "admin"},
    )
    token = login.json()["token"]

    response = await api_client.post(
        f"/api/admin/groups/{group.id}/summaries/generate",
        json={"summary_date": "2026-04-26", "deliver": False},
        headers={"Authorization": f"Bearer {token}", "X-App-Boundary": "admin"},
    )

    assert response.status_code == 200
    assert response.json()["summary_date"] == "2026-04-26"


@pytest.mark.asyncio
async def test_manual_generate_endpoint_rejects_non_admin(api_client, db_session) -> None:
    group = Group(tg_group_id=-1007712, title="API Summary Group 2", is_active=True)
    db_session.add(group)
    await db_session.commit()

    login = await api_client.post(
        "/api/auth/miniapp/token",
        json={"init_data": _webapp_init_data(user_id=84521)},
        headers={"X-App-Boundary": "admin"},
    )
    token = login.json()["token"]

    response = await api_client.post(
        f"/api/admin/groups/{group.id}/summaries/generate",
        json={"summary_date": "2026-04-26", "deliver": False},
        headers={"Authorization": f"Bearer {token}", "X-App-Boundary": "admin"},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_summary_settings_endpoint_round_trip(api_client, db_session) -> None:
    group = Group(tg_group_id=-1007713, title="Settings Summary Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=84522, role="owner"))
    await db_session.commit()

    login = await api_client.post(
        "/api/auth/miniapp/token",
        json={"init_data": _webapp_init_data(user_id=84522)},
        headers={"X-App-Boundary": "admin"},
    )
    token = login.json()["token"]
    headers = {"Authorization": f"Bearer {token}", "X-App-Boundary": "admin"}

    put_response = await api_client.put(
        f"/api/admin/groups/{group.id}/summaries/settings",
        json={"enabled": True, "summary_time": "20:30", "timezone": "Asia/Aden", "delivery_mode": "dashboard_only", "max_message_samples": 250},
        headers=headers,
    )
    get_response = await api_client.get(f"/api/admin/groups/{group.id}/summaries/settings", headers=headers)

    assert put_response.status_code == 200
    assert get_response.status_code == 200
    assert get_response.json()["enabled"] is True
    assert get_response.json()["summary_time"] == "20:30"
