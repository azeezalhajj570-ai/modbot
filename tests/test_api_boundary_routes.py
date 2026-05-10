from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from bot.config import get_settings
from bot.dashboard.api.main import app
from bot.db.models import Agent, Group, GroupAdminRole, Warning


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


@pytest_asyncio.fixture
async def api_client(patch_db_dependencies) -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_api_auth_me_alias_returns_identity_profile(api_client, db_session) -> None:
    group = Group(tg_group_id=-10099101, title="Auth Alias Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=9901, role="owner"))
    await db_session.commit()

    response = await api_client.get(
        "/api/auth/me",
        headers={
            "X-Telegram-Init-Data": _webapp_init_data(user_id=9901),
            "X-App-Boundary": "admin",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["user"]["id"] == 9901
    assert payload["groups"][0]["title"] == "Auth Alias Group"


@pytest.mark.asyncio
async def test_boundary_miniapp_token_uses_telegram_identity(api_client, db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTS_BOT_TOKEN", "123456:AGENTSTOKEN")
    get_settings.cache_clear()

    group = Group(tg_group_id=-10099107, title="Agents Token Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=9907, role="owner"))
    await db_session.commit()

    login = await api_client.post(
        "/api/auth/miniapp/token",
        json={"init_data": _webapp_init_data(user_id=9907, bot_token="123456:AGENTSTOKEN")},
        headers={"X-App-Boundary": "agents"},
    )
    assert login.status_code == 200

    response = await api_client.get(
        "/api/auth/me",
        headers={
            "Authorization": f"Bearer {login.json()['token']}",
            "X-App-Boundary": "agents",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["user"]["id"] == 9907
    assert payload["groups"][0]["title"] == "Agents Token Group"

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_canonical_and_api_auth_routes_share_provider_and_login_contracts(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TELEGRAM_LOGIN_BOT_USERNAME", "combot_test_bot")
    monkeypatch.setenv(
        "DASHBOARD_BROWSER_USERS",
        json.dumps(
            [
                {
                    "email": "owner@example.com",
                    "password": "secret123",
                    "user_id": 9910,
                    "username": "owner",
                    "first_name": "Compat",
                    "last_name": "Owner",
                }
            ]
        ),
    )
    get_settings.cache_clear()

    canonical_providers = await api_client.get("/auth/providers")
    legacy_providers = await api_client.get("/api/auth/providers")
    assert canonical_providers.status_code == 200
    assert legacy_providers.status_code == 200
    assert canonical_providers.json() == legacy_providers.json()

    canonical_login = await api_client.post("/auth/email/login", json={"email": "owner", "password": "secret123"})
    boundary_login = await api_client.post("/api/auth/email/login", json={"email": "owner", "password": "secret123"})
    assert canonical_login.status_code == 200
    assert boundary_login.status_code == 200
    assert canonical_login.json().keys() == boundary_login.json().keys()

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_shared_auth_boundary_routes_remain_mounted(api_client, db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_LOGIN_BOT_USERNAME", "combot_test_bot")
    monkeypatch.setenv("BOT_OWNER_IDS", "9911")
    get_settings.cache_clear()

    group = Group(tg_group_id=-10099111, title="Legacy Auth Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=9911, role="owner"))
    await db_session.commit()

    # Clear cache again to be sure dependencies see the owner
    get_settings.cache_clear()

    providers = await api_client.get("/auth/providers")
    assert providers.status_code == 200
    assert providers.json()["telegram"]["bot_username"] == "combot_test_bot"

    me = await api_client.get(
        "/webapp/auth/me",
        headers={
            "X-Telegram-Init-Data": _webapp_init_data(user_id=9911),
            "X-App-Boundary": "admin",
        },
    )
    assert me.status_code == 200
    assert me.json()["groups"][0]["title"] == "Legacy Auth Group"

    install_groups = await api_client.get(
        "/webapp/bot/install-groups",
        headers={
            "X-Telegram-Init-Data": _webapp_init_data(user_id=9911),
            "X-App-Boundary": "admin",
        },
    )
    assert install_groups.status_code == 200
    assert install_groups.json()[0]["tg_group_id"] == group.tg_group_id

    removed_login = await api_client.post("/api/auth/login", json={"email": "owner", "password": "secret123"})
    assert removed_login.status_code == 401
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_api_internal_groups_alias_returns_groups(api_client, db_session) -> None:
    db_session.add(Group(tg_group_id=-10099102, title="Internal Alias Group", is_active=True))
    await db_session.commit()

    response = await api_client.get("/api/internal/groups")
    assert response.status_code == 200
    assert any(row["title"] == "Internal Alias Group" for row in response.json())


@pytest.mark.asyncio
async def test_api_admin_overview_alias_returns_group_stats(api_client, db_session) -> None:
    group = Group(tg_group_id=-10099103, title="Admin Overview Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=9903, role="owner"))
    await db_session.commit()

    response = await api_client.get(
        f"/api/admin/groups/{group.id}/overview",
        headers={
            "X-Telegram-Init-Data": _webapp_init_data(user_id=9903),
            "X-App-Boundary": "admin",
        },
    )
    assert response.status_code == 200
    assert response.json()["group"]["title"] == "Admin Overview Group"


@pytest.mark.asyncio
async def test_api_admin_moderation_actions_alias_uses_runtime_service(api_client, db_session, monkeypatch, fake_bot) -> None:
    group = Group(tg_group_id=-10099104, title="Admin Moderation Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=9904, role="owner"))
    db_session.add(Warning(group_id=group.id, user_id=77, issued_by=9904, reason="spam", count=1))
    await db_session.commit()

    monkeypatch.setattr("bot.core.runtime.moderation.Bot", lambda token: fake_bot)
    headers = {
        "X-Telegram-Init-Data": _webapp_init_data(user_id=9904),
        "X-App-Boundary": "admin",
    }

    approve = await api_client.post(
        f"/api/admin/groups/{group.id}/moderation/actions",
        headers=headers,
        json={"user_id": 77, "action": "approve", "reason": "cleared"},
    )
    warn = await api_client.post(
        f"/api/admin/groups/{group.id}/moderation/actions",
        headers=headers,
        json={"user_id": 77, "action": "warn", "reason": "new issue"},
    )

    assert approve.status_code == 200
    assert warn.status_code == 200


@pytest.mark.asyncio
async def test_api_agents_alias_lists_group_agents(api_client, db_session) -> None:
    group = Group(tg_group_id=-10099105, title="Agents Alias Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=9905, role="owner"))
    db_session.add(
        Agent(
            group_id=group.id,
            telegram_user_id=9905,
            external_account_id="agent-9905",
            auth_state="active",
            status="active",
            details={"label": "primary"},
        )
    )
    await db_session.commit()

    response = await api_client.get(
        "/api/agents",
        params={"group_id": group.id},
        headers={
            "X-Telegram-Init-Data": _webapp_init_data(user_id=9905),
            "X-App-Boundary": "admin",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["group_id"] == group.id
    assert payload[0]["external_account_id"] == "agent-9905"


@pytest.mark.asyncio
async def test_api_admin_task_catalog_alias_returns_catalog(api_client, db_session) -> None:
    group = Group(tg_group_id=-10099106, title="Admin Tasks Alias Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=9906, role="owner"))
    await db_session.commit()

    response = await api_client.get(
        "/api/admin/tasks/catalog",
        headers={
            "X-Telegram-Init-Data": _webapp_init_data(user_id=9906),
            "X-App-Boundary": "admin",
        },
    )
    assert response.status_code == 200
    assert any(item["key"] == "reply_message" for item in response.json())
