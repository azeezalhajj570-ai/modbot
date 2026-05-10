from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from bot.config import get_settings
from bot.dashboard.api.main import app
from bot.db.models import Group, OwnerAuditLog, PrivateAccessRequirement, SubscriptionRequest, SubscriptionStatus


@pytest_asyncio.fixture
async def api_client(patch_db_dependencies) -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def _webapp_init_data(*, user_id: int) -> str:
    bot_token = get_settings().bot_token
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
async def test_disable_group_creates_owner_audit_log(api_client, db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_OWNER_IDS", "9092")
    get_settings.cache_clear()
    group = Group(tg_group_id=-1009001, title="Audited Group", is_active=True)
    db_session.add(group)
    await db_session.commit()

    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=9092)}
    response = await api_client.post(f"/webapp/owner/groups/{group.id}/disable", headers=headers)

    assert response.status_code == 200
    rows = (await db_session.execute(select(OwnerAuditLog).order_by(OwnerAuditLog.id.asc()))).scalars().all()
    assert len(rows) == 1
    assert rows[0].actor_id == 9092
    assert rows[0].action == "disable_group"
    assert rows[0].target_type == "group"
    assert rows[0].target_id == str(group.id)


@pytest.mark.asyncio
async def test_approve_subscription_creates_owner_audit_log(
    api_client,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
    fake_bot,
) -> None:
    owner_id = 6816159624
    monkeypatch.setenv("BOT_OWNER_IDS", str(owner_id))
    get_settings.cache_clear()
    monkeypatch.setattr("bot.dashboard.api.owner.Bot", lambda token: fake_bot)
    request = SubscriptionRequest(
        tg_user_id=2222,
        username="requester",
        full_name="Request User",
        message="Please onboard us",
        status=SubscriptionStatus.PENDING.value,
    )
    db_session.add(request)
    await db_session.commit()

    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=owner_id)}
    response = await api_client.post(
        f"/webapp/owner/subscriptions/{request.id}",
        headers=headers,
        json={"status": "approved", "response": "Welcome aboard"},
    )

    assert response.status_code == 200
    rows = (await db_session.execute(select(OwnerAuditLog).order_by(OwnerAuditLog.id.asc()))).scalars().all()
    assert len(rows) == 1
    assert rows[0].actor_id == owner_id
    assert rows[0].action == "approve_subscription"
    assert rows[0].target_type == "subscription"
    assert rows[0].target_id == str(request.id)


@pytest.mark.asyncio
async def test_cancel_subscription_creates_owner_audit_log(
    api_client,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
    fake_bot,
) -> None:
    owner_id = 6816159625
    monkeypatch.setenv("BOT_OWNER_IDS", str(owner_id))
    get_settings.cache_clear()
    monkeypatch.setattr("bot.dashboard.api.owner.Bot", lambda token: fake_bot)
    request = SubscriptionRequest(
        tg_user_id=2223,
        username="requester",
        full_name="Request User",
        message="Please onboard us",
        status=SubscriptionStatus.APPROVED.value,
    )
    db_session.add(request)
    await db_session.commit()

    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=owner_id)}
    response = await api_client.post(
        f"/webapp/owner/subscriptions/{request.id}",
        headers=headers,
        json={"status": "cancelled", "response": "Access removed"},
    )

    assert response.status_code == 200
    rows = (await db_session.execute(select(OwnerAuditLog).order_by(OwnerAuditLog.id.asc()))).scalars().all()
    assert len(rows) == 1
    assert rows[0].actor_id == owner_id
    assert rows[0].action == "cancel_subscription"
    assert rows[0].target_type == "subscription"
    assert rows[0].target_id == str(request.id)


@pytest.mark.asyncio
async def test_owner_audit_log_returns_descending_entries(api_client, db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_OWNER_IDS", "9093")
    get_settings.cache_clear()
    db_session.add(
        OwnerAuditLog(actor_id=9093, action="first", target_type="group", target_id="1", detail=None)
    )
    db_session.add(
        OwnerAuditLog(actor_id=9093, action="second", target_type="subscription", target_id="2", detail=None)
    )
    await db_session.commit()

    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=9093)}
    response = await api_client.get("/webapp/owner/audit-log", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["action"] == "second"
    assert payload[1]["action"] == "first"


@pytest.mark.asyncio
async def test_update_private_access_gate_creates_owner_audit_log(api_client, db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_OWNER_IDS", "9094")
    get_settings.cache_clear()
    group = Group(tg_group_id=-1009002, title="Gate Group", is_active=True)
    db_session.add(group)
    db_session.add(PrivateAccessRequirement(required_group_tg_id=group.tg_group_id - 1))
    await db_session.commit()

    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=9094)}
    response = await api_client.patch(
        "/webapp/owner/private-access-gate",
        headers=headers,
        json={"required_group_tg_ids": [group.tg_group_id]},
    )

    assert response.status_code == 200
    rows = (await db_session.execute(select(OwnerAuditLog).order_by(OwnerAuditLog.id.asc()))).scalars().all()
    assert len(rows) == 1
    assert rows[0].actor_id == 9094
    assert rows[0].action == "update_private_access_gate"
    assert rows[0].target_type == "private_access_gate"
    assert rows[0].target_id == "global"


@pytest.mark.asyncio
async def test_non_owner_cannot_access_owner_audit_log(api_client) -> None:
    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=5555)}
    response = await api_client.get("/webapp/owner/audit-log", headers=headers)

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_owner_route_uses_shared_identity_extraction(api_client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_OWNER_IDS", "777001")
    get_settings.cache_clear()

    response = await api_client.get(
        "/webapp/owner/audit-log",
        headers={"X-Telegram-Init-Data": _webapp_init_data(user_id=777001)},
    )

    assert response.status_code == 200
