from __future__ import annotations

import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from bot.config import get_settings
from bot.dashboard.api.main import app
from bot.db.models import (
    Agent,
    AgentNotification,
    Group,
    GroupAdminRole,
    GroupSetting,
    ModerationLog,
    PrivateAccessRequirement,
    PluginEnabled,
    ScrapedGroup,
    ScrapedMember,
    ScrapedMessage,
    SubscriptionRequest,
    SubscriptionStatus,
    User,
    Warning,
)
from bot.services.admin_group_member_service import AdminGroupMemberSearchRateLimitedError


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


def _telegram_login_payload(*, user_id: int, auth_date: int | None = None, bot_token: str = "123456:TESTTOKEN") -> dict[str, str]:
    payload = {
        "id": str(user_id),
        "username": f"user{user_id}",
        "first_name": "Test",
        "auth_date": str(auth_date or int(time.time())),
    }
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(payload.items()))
    secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()
    payload["hash"] = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    return payload


@pytest.mark.asyncio
async def test_get_groups(api_client, db_session) -> None:
    db_session.add(Group(tg_group_id=-1002001, title="API Group", is_active=True))
    await db_session.commit()

    response = await api_client.get("/groups")
    assert response.status_code == 200
    payload = response.json()
    assert any(g["title"] == "API Group" for g in payload)


@pytest.mark.asyncio
async def test_get_group_settings(api_client, db_session) -> None:
    group = Group(tg_group_id=-1002002, title="Settings Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupSetting(group_id=group.id, key="anti_links", value={"value": True}))
    await db_session.commit()

    response = await api_client.get(f"/settings/{group.id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["key"] == "anti_links"
    assert payload[0]["value"] is True


@pytest.mark.asyncio
async def test_post_plugins_enable_updates_database(api_client, db_session) -> None:
    group = Group(tg_group_id=-1002003, title="Plugin Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    await db_session.commit()

    response = await api_client.post(
        "/plugins/enable",
        json={"group_id": group.id, "plugin_name": "anti_links", "enabled": True},
    )
    assert response.status_code == 200

    plugins = await api_client.get(f"/groups/{group.id}/plugins")
    assert plugins.status_code == 200
    assert plugins.json() == [{"plugin_name": "anti_links", "enabled": True}]


@pytest.mark.asyncio
async def test_group_warnings_endpoint(api_client, db_session) -> None:
    group = Group(tg_group_id=-1002004, title="Warn Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(Warning(group_id=group.id, user_id=444, issued_by=111, reason="spam", count=2))
    await db_session.commit()

    response = await api_client.get(f"/groups/{group.id}/warnings")
    assert response.status_code == 200
    data = response.json()
    assert data[0]["reason"] == "spam"


@pytest.mark.asyncio
async def test_settings_schema_endpoint(api_client) -> None:
    response = await api_client.get("/settings/schema")
    assert response.status_code == 200
    payload = response.json()
    assert "anti_links" in payload
    assert "semantic_assistant" in payload
    keys = {entry["key"] for entry in payload["anti_links"]}
    assert "anti_spam" in keys
    assert "anti_ads" in keys
    assert "anti_spam_mute" in keys
    assert "anti_spam_mute_limit" in keys
    assert "anti_ads_mute" in keys
    assert "anti_ads_mute_limit" in keys
    assert "warn_auto_remove" in keys
    assert "warn_remove_limit" in keys
    semantic_keys = {entry["key"] for entry in payload["semantic_assistant"]}
    assert "semantic_assistant_top_k" in semantic_keys


@pytest.mark.asyncio
async def test_webapp_auth_me_requires_valid_init_data(api_client) -> None:
    response = await api_client.get("/webapp/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_browser_telegram_login_returns_jwt_and_loads_dashboard_profile(api_client, db_session) -> None:
    group = Group(tg_group_id=-1008801, title="Browser Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=8123, role="owner"))
    await db_session.commit()

    login = await api_client.post("/auth/telegram/login", json=_telegram_login_payload(user_id=8123))
    assert login.status_code == 200
    token = login.json()["token"]

    me = await api_client.get("/webapp/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    payload = me.json()
    assert payload["user"]["id"] == 8123
    assert payload["groups"] == [
        {
            "id": group.id,
            "title": "Browser Group",
            "tg_group_id": -1008801,
            "role": "owner",
        }
    ]

    user = (await db_session.execute(select(User).where(User.tg_user_id == 8123))).scalar_one_or_none()
    assert user is not None
    assert user.username == "user8123"


@pytest.mark.asyncio
async def test_browser_telegram_login_rejects_expired_payload(api_client) -> None:
    response = await api_client.post(
        "/auth/telegram/login",
        json=_telegram_login_payload(user_id=8124, auth_date=int(time.time()) - 90_000),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_miniapp_token_accepts_agents_bot_token(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123456:LEGACYTOKEN")
    monkeypatch.setenv("ADMIN_BOT_TOKEN", "123456:ADMINTOKEN")
    monkeypatch.setenv("AGENTS_BOT_TOKEN", "123456:AGENTSTOKEN")
    get_settings.cache_clear()

    response = await api_client.post(
        "/api/auth/miniapp/token",
        json={"init_data": _webapp_init_data(user_id=8451, bot_token="123456:AGENTSTOKEN")},
        headers={"X-App-Boundary": "agents"},
    )

    assert response.status_code == 200
    assert response.json()["token"]

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_admin_routes_require_admin_boundary(api_client, db_session) -> None:
    user = User(tg_user_id=8452, username="user8452", full_name="Admin User")
    db_session.add(user)
    await db_session.flush()

    from bot.db.models.subscription import SubscriptionRequest
    db_session.add(SubscriptionRequest(tg_user_id=8452, status="approved", plan="pro"))

    group = Group(tg_group_id=-1008811, title="Admin Boundary Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=user.id, role="owner"))
    await db_session.commit()

    login = await api_client.post(
        "/api/auth/miniapp/token",
        json={"init_data": _webapp_init_data(user_id=8452)},
        headers={"X-App-Boundary": "admin"},
    )
    token = login.json()["token"]

    allowed = await api_client.get(
        f"/api/admin/groups/{group.id}/overview",
        headers={"Authorization": f"Bearer {token}", "X-App-Boundary": "admin"},
    )
    denied = await api_client.get(
        f"/api/admin/groups/{group.id}/overview",
        headers={"Authorization": f"Bearer {token}", "X-App-Boundary": "agents"},
    )

    assert allowed.status_code == 200
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_agents_routes_require_agents_boundary(api_client, db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_OWNER_IDS", "8453")
    get_settings.cache_clear()

    user = User(tg_user_id=8453, username="user8453", full_name="Agents User")
    db_session.add(user)
    await db_session.flush()

    group = Group(tg_group_id=-1008812, title="Agents Boundary Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=user.id, role="owner"))
    await db_session.commit()

    login = await api_client.post(
        "/api/auth/miniapp/token",
        json={"init_data": _webapp_init_data(user_id=8453)},
        headers={"X-App-Boundary": "agents"},
    )
    token = login.json()["token"]

    allowed = await api_client.get(
        "/api/agents",
        params={"group_id": group.id},
        headers={"Authorization": f"Bearer {token}", "X-App-Boundary": "agents"},
    )
    denied = await api_client.get(
        "/api/agents",
        params={"group_id": group.id},
        headers={"Authorization": f"Bearer {token}", "X-App-Boundary": "admin"},
    )

    assert allowed.status_code == 200
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_webapp_root_redirects_to_admin_shell(api_client) -> None:
    response = await api_client.get("/webapp", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/webapp/admin"


@pytest.mark.asyncio
async def test_webapp_agents_shell_is_public_and_list_alias_remains_protected(api_client) -> None:
    shell = await api_client.get("/webapp/agents")
    assert shell.status_code == 200
    assert "text/html" in shell.headers["content-type"]

    list_alias = await api_client.get("/webapp/agents/list")
    assert list_alias.status_code == 401


@pytest.mark.asyncio
async def test_email_password_login_returns_jwt_and_loads_dashboard_profile(
    api_client,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DASHBOARD_BROWSER_USERS",
        json.dumps(
            [
                {
                    "email": "owner@example.com",
                    "password": "secret123",
                    "user_id": 8127,
                    "username": "browser_owner",
                    "first_name": "Browser",
                    "last_name": "Owner",
                }
            ]
        ),
    )
    get_settings.cache_clear()

    group = Group(tg_group_id=-1008807, title="Email Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=8127, role="owner"))
    await db_session.commit()

    login = await api_client.post("/auth/email/login", json={"email": "owner@example.com", "password": "secret123"})
    assert login.status_code == 200
    token = login.json()["token"]

    me = await api_client.get("/webapp/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    payload = me.json()
    assert payload["user"]["id"] == 8127
    assert payload["user"]["username"] == "browser_owner"
    assert payload["groups"][0]["title"] == "Email Group"

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_email_password_login_accepts_configured_username(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DASHBOARD_BROWSER_USERS",
        json.dumps(
            [
                {
                    "email": "owner@example.com",
                    "password": "secret123",
                    "user_id": 8128,
                    "username": "owner",
                    "first_name": "Bot",
                    "last_name": "Owner",
                }
            ]
        ),
    )
    get_settings.cache_clear()

    login = await api_client.post("/auth/email/login", json={"email": "owner", "password": "secret123"})
    assert login.status_code == 200
    assert login.json()["token"]

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_removed_api_auth_compatibility_login_routes_return_not_found(
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
                    "user_id": 9001,
                    "username": "owner",
                    "first_name": "Bot",
                    "last_name": "Owner",
                }
            ]
        ),
    )
    get_settings.cache_clear()

    login = await api_client.post("/api/auth/login", json={"username": "owner", "password": "secret123"})
    assert login.status_code == 404

    telegram_login = await api_client.post("/api/auth/telegram-login", json=_telegram_login_payload(user_id=9002))
    assert telegram_login.status_code == 404

    miniapp_token = await api_client.post(
        "/api/auth/miniapp/token",
        json={"init_data": _webapp_init_data(user_id=9003)},
    )
    assert miniapp_token.status_code == 200
    assert miniapp_token.json()["token"]

    miniapp_login = await api_client.post(
        "/api/auth/miniapp-login",
        json={"init_data": _webapp_init_data(user_id=9003)},
    )
    assert miniapp_login.status_code == 200
    assert miniapp_login.json()["token"]

    email_login = await api_client.post("/api/auth/email/login", json={"email": "owner", "password": "secret123"})
    assert email_login.status_code == 200
    assert email_login.json()["token"]

    providers = await api_client.get("/api/auth/providers")
    assert providers.status_code == 200
    assert providers.json()["password"]["enabled"] is True

    profile_alias = await api_client.get(
        "/api/auth/me",
        headers={"X-Telegram-Init-Data": _webapp_init_data(user_id=9002)},
    )
    assert profile_alias.status_code == 200
    assert profile_alias.json()["user"]["id"] == 9002

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_owner_routes_accept_browser_jwt(api_client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_OWNER_IDS", "8126")
    get_settings.cache_clear()

    login = await api_client.post("/auth/telegram/login", json=_telegram_login_payload(user_id=8126))
    assert login.status_code == 200

    response = await api_client.get(
        "/webapp/owner/stats",
        headers={"Authorization": f"Bearer {login.json()['token']}"},
    )
    assert response.status_code == 200
    assert "total_groups" in response.json()

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_owner_subscription_update_accepts_legacy_action_payload(
    api_client,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
    fake_bot,
) -> None:
    monkeypatch.setenv("BOT_OWNER_IDS", "9200")
    get_settings.cache_clear()
    monkeypatch.setattr("bot.dashboard.api.owner.Bot", lambda token: fake_bot)

    request = SubscriptionRequest(
        tg_user_id=3333,
        username="legacy-owner",
        full_name="Legacy Owner",
        status=SubscriptionStatus.PENDING,
    )
    db_session.add(request)
    await db_session.commit()

    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=9200)}
    response = await api_client.post(
        f"/webapp/owner/subscriptions/{request.id}",
        headers=headers,
        json={"action": "approve", "response": "Legacy client"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert response.json()["response"] == "Legacy client"

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_webapp_notification_reports_returns_logged_notify_entries(api_client, db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_OWNER_IDS", "9911")
    get_settings.cache_clear()

    user = User(tg_user_id=9911, username="user9911")
    db_session.add(user)
    await db_session.flush()

    group = Group(tg_group_id=-1007201, title="Notify Reports", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=user.id, role="owner"))
    db_session.add(
        ModerationLog(
            group_id=group.id,
            action="destination_notified",
            target_user_id=4444,
            admin_user_id=None,
            reason="pricing",
            details={
                "task_key": "notify_destination",
                "assignment_id": "notify-1",
                "message_text": "Need pricing today",
                "destination": "-100999",
                "delivery_mode": "text_and_forward",
                "source_chat_id": str(group.tg_group_id),
                "source_group_title": group.title,
                "source_message_id": "77",
                "source_user_id": "4444",
            },
        )
    )
    await db_session.commit()

    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=9911)}
    response = await api_client.get(f"/webapp/groups/{group.id}/notification-reports", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["user_id"] == 4444
    assert payload[0]["message_text"] == "Need pricing today"
    assert payload[0]["source_group_title"] == "Notify Reports"
    assert payload[0]["destination"] == "-100999"


@pytest.mark.asyncio
async def test_webapp_notification_reports_reply_sends_message(api_client, db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_OWNER_IDS", "9912")
    get_settings.cache_clear()

    user = User(tg_user_id=9912, username="user9912")
    db_session.add(user)
    await db_session.flush()

    group = Group(tg_group_id=-1007202, title="Reply Report Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=user.id, role="owner"))
    log_entry = ModerationLog(
        group_id=group.id,
        action="destination_notified",
        target_user_id=5555,
        admin_user_id=None,
        reason="support",
        details={
            "task_key": "notify_destination",
            "assignment_id": "notify-2",
            "message_text": "Please help",
            "destination": "-100777",
            "delivery_mode": "text",
            "source_chat_id": str(group.tg_group_id),
            "source_group_title": group.title,
            "source_message_id": "88",
            "source_user_id": "5555",
        },
    )
    db_session.add(log_entry)
    await db_session.commit()

    sent_calls: list[dict[str, int | str | None]] = []

    class FakeBot:
        def __init__(self, *args, **kwargs) -> None:
            self.session = SimpleNamespace(close=self._close)

        async def send_message(self, chat_id: int, text: str, reply_to_message_id: int | None = None):
            sent_calls.append(
                {
                    "chat_id": chat_id,
                    "text": text,
                    "reply_to_message_id": reply_to_message_id,
                }
            )
            return SimpleNamespace(message_id=321)

        async def _close(self) -> None:
            return None

    monkeypatch.setattr("bot.services.admin_activity_service.Bot", FakeBot)

    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=9912)}
    response = await api_client.post(
        f"/webapp/groups/{group.id}/notification-reports/{log_entry.id}/reply",
        headers=headers,
        json={"text": "We are checking this now."},
    )

    assert response.status_code == 200
    assert sent_calls == [
        {
            "chat_id": -100777,
            "text": "We are checking this now.",
            "reply_to_message_id": 88,
        }
    ]
    rows = (
        await db_session.execute(
            select(ModerationLog).where(
                ModerationLog.group_id == group.id,
                ModerationLog.action == "notification_report_reply",
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].details["source_log_id"] == log_entry.id


@pytest.mark.asyncio
async def test_webapp_auth_me_backfills_admin_role_from_telegram(
    api_client,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
    fake_bot,
) -> None:
    group = Group(tg_group_id=-1007000, title="Recovered Group", is_active=True)
    db_session.add(group)
    await db_session.commit()

    fake_bot.chat_members[(group.tg_group_id, 4444)] = SimpleNamespace(status="administrator")
    monkeypatch.setattr("bot.core.runtime.moderation.Bot", lambda token: fake_bot)
    monkeypatch.setattr("bot.core.runtime.moderation.Bot", lambda token: fake_bot)
    monkeypatch.setattr("bot.dashboard.api.dependencies.Bot", lambda token: fake_bot)
    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=4444)}

    response = await api_client.get("/webapp/auth/me", headers=headers)
    assert response.status_code == 200

    payload = response.json()
    assert payload["groups"] == [
        {
            "id": group.id,
            "title": "Recovered Group",
            "tg_group_id": -1007000,
            "role": "admin",
        }
    ]

    role = (
        await db_session.execute(
            select(GroupAdminRole).where(GroupAdminRole.group_id == group.id, GroupAdminRole.user_id == 4444)
        )
    ).scalar_one_or_none()
    assert role is not None
    assert role.role == "admin"


@pytest.mark.asyncio
async def test_webapp_auth_me_backfills_group_from_install_candidates(
    api_client,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
    fake_bot,
) -> None:
    async def fake_candidates(session, *, identity):
        assert identity.user_id == 4545
        return [
            {
                "managed_group_id": None,
                "tg_group_id": -10084545,
                "title": "Fresh Workspace",
                "role": "owner",
                "is_managed": False,
            }
        ]

    monkeypatch.setattr("bot.core.runtime.moderation.Bot", lambda token: fake_bot)
    monkeypatch.setattr("bot.core.runtime.moderation.Bot", lambda token: fake_bot)
    monkeypatch.setattr("bot.dashboard.api.dependencies.Bot", lambda token: fake_bot)
    monkeypatch.setattr("bot.dashboard.api.dependencies.list_identity_bot_install_groups", fake_candidates)
    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=4545)}

    response = await api_client.get("/webapp/auth/me", headers=headers)
    assert response.status_code == 200

    payload = response.json()
    assert payload["groups"] == [
        {
            "id": payload["groups"][0]["id"],
            "title": "Fresh Workspace",
            "tg_group_id": -10084545,
            "role": "owner",
        }
    ]

    group = (await db_session.execute(select(Group).where(Group.tg_group_id == -10084545))).scalar_one_or_none()
    assert group is not None
    role = (
        await db_session.execute(
            select(GroupAdminRole).where(GroupAdminRole.group_id == group.id, GroupAdminRole.user_id == 4545)
        )
    ).scalar_one_or_none()
    assert role is not None
    assert role.role == "owner"


@pytest.mark.asyncio
async def test_webapp_group_settings_flow(api_client, db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_OWNER_IDS", "4444")
    get_settings.cache_clear()

    user = User(tg_user_id=4444, username="user4444")
    db_session.add(user)
    await db_session.flush()

    group = Group(tg_group_id=-1007001, title="WebApp Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=user.id, role="owner"))
    await db_session.commit()

    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=4444)}

    get_resp = await api_client.get(f"/webapp/groups/{group.id}/settings", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["settings"] == {}

    patch_resp = await api_client.patch(
        f"/webapp/groups/{group.id}/settings",
        headers=headers,
        json={"settings": {"anti_spam": True, "welcome_message": "Hello"}},
    )
    assert patch_resp.status_code == 200

    verify = await api_client.get(f"/webapp/groups/{group.id}/settings", headers=headers)
    assert verify.status_code == 200
    assert verify.json()["settings"]["anti_spam"] is True
    assert verify.json()["settings"]["welcome_message"] == "Hello"


@pytest.mark.asyncio
async def test_webapp_forbids_non_admin_access(api_client, db_session) -> None:
    group = Group(tg_group_id=-1007002, title="Forbidden Group", is_active=True)
    db_session.add(group)
    await db_session.commit()

    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=5555)}
    response = await api_client.get(f"/webapp/groups/{group.id}/overview", headers=headers)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_webapp_auth_me_marks_bot_owner(api_client, db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_OWNER_IDS", "9090")
    get_settings.cache_clear()
    group = Group(tg_group_id=-1007990, title="Owner Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=9090, role="owner"))
    await db_session.commit()

    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=9090)}
    response = await api_client.get("/webapp/auth/me", headers=headers)

    assert response.status_code == 200
    assert response.json()["is_bot_owner"] is True


@pytest.mark.asyncio
async def test_webapp_bot_install_links_returns_selected_groups(
    api_client,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
    fake_bot,
) -> None:
    group_one = Group(tg_group_id=-1008101, title="Alpha Group", is_active=True)
    group_two = Group(tg_group_id=-1008102, title="Beta Group", is_active=True)
    db_session.add(group_one)
    db_session.add(group_two)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group_one.id, user_id=4444, role="owner"))
    db_session.add(GroupAdminRole(group_id=group_two.id, user_id=4444, role="admin"))
    await db_session.commit()

    monkeypatch.setattr("bot.dashboard.api.dependencies.Bot", lambda token: fake_bot)
    monkeypatch.setattr("bot.core.runtime.moderation.Bot", lambda token: fake_bot)
    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=4444)}
    response = await api_client.post(
        "/webapp/bot/install-links",
        headers=headers,
        json={
            "group_ids": [group_two.id, group_one.id],
            "permissions": ["delete_messages", "restrict_members", "invite_users"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["bot_username"] == "combot_test_bot"
    assert payload["manual_confirmation_required"] is True
    assert payload["links"] == [
        {
            "group_id": group_two.id,
            "tg_group_id": group_two.tg_group_id,
            "title": "Beta Group",
            "url": "https://t.me/combot_test_bot?startgroup=true&admin=delete_messages+restrict_members+invite_users",
        },
        {
            "group_id": group_one.id,
            "tg_group_id": group_one.tg_group_id,
            "title": "Alpha Group",
            "url": "https://t.me/combot_test_bot?startgroup=true&admin=delete_messages+restrict_members+invite_users",
        },
    ]


@pytest.mark.asyncio
async def test_webapp_bot_install_links_rejects_unmanaged_groups(
    api_client,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
    fake_bot,
) -> None:
    group = Group(tg_group_id=-1008103, title="Managed Group", is_active=True)
    unmanaged = Group(tg_group_id=-1008104, title="Unmanaged Group", is_active=True)
    db_session.add(group)
    db_session.add(unmanaged)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=4444, role="owner"))
    await db_session.commit()

    monkeypatch.setattr("bot.dashboard.api.dependencies.Bot", lambda token: fake_bot)
    monkeypatch.setattr("bot.core.runtime.moderation.Bot", lambda token: fake_bot)
    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=4444)}
    response = await api_client.post(
        "/webapp/bot/install-links",
        headers=headers,
        json={
            "group_ids": [group.id, unmanaged.id],
            "permissions": ["delete_messages"],
        },
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_webapp_bot_install_groups_returns_session_candidates(
    api_client,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    managed_group = Group(tg_group_id=-1008105, title="Managed Group", is_active=True)
    db_session.add(managed_group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=managed_group.id, user_id=4444, role="owner"))
    await db_session.commit()

    async def fake_candidates(session, *, identity):
        assert identity.user_id == 4444
        return [
            {
                "managed_group_id": managed_group.id,
                "tg_group_id": managed_group.tg_group_id,
                "title": managed_group.title,
                "role": "owner",
                "is_managed": True,
            },
            {
                "managed_group_id": None,
                "tg_group_id": -1008999,
                "title": "Fresh Group",
                "role": "admin",
                "is_managed": False,
            },
        ]

    monkeypatch.setattr("bot.dashboard.api.routers.auth.list_identity_bot_install_groups", fake_candidates)
    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=4444)}

    response = await api_client.get("/webapp/bot/install-groups", headers=headers)

    assert response.status_code == 200
    assert response.json() == [
        {
            "managed_group_id": managed_group.id,
            "tg_group_id": managed_group.tg_group_id,
            "title": "Managed Group",
            "role": "owner",
            "is_managed": True,
        },
        {
            "managed_group_id": None,
            "tg_group_id": -1008999,
            "title": "Fresh Group",
            "role": "admin",
            "is_managed": False,
        },
    ]


@pytest.mark.asyncio
async def test_webapp_bot_install_links_accepts_session_groups(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
    fake_bot,
) -> None:
    monkeypatch.setenv("TELEGRAM_LOGIN_BOT_USERNAME", "combot_test_bot")
    get_settings.cache_clear()

    async def fake_candidates(session, *, identity):
        assert identity.user_id == 4444
        return [
            {
                "managed_group_id": None,
                "tg_group_id": -1008999,
                "title": "Fresh Group",
                "role": "admin",
                "is_managed": False,
            },
            {
                "managed_group_id": 7,
                "tg_group_id": -1008101,
                "title": "Managed Group",
                "role": "owner",
                "is_managed": True,
            },
        ]

    monkeypatch.setattr("bot.dashboard.api.routers.auth.list_identity_bot_install_groups", fake_candidates)
    monkeypatch.setattr("bot.dashboard.api.dependencies.Bot", lambda token: fake_bot)
    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=4444)}

    response = await api_client.post(
        "/webapp/bot/install-links",
        headers=headers,
        json={
            "groups": [
                {"tg_group_id": -1008999, "title": "Fresh Group"},
                {"tg_group_id": -1008101, "title": "Managed Group"},
            ],
            "permissions": ["delete_messages"],
        },
    )

    assert response.status_code == 200
    assert response.json()["links"] == [
        {
            "group_id": None,
            "tg_group_id": -1008999,
            "title": "Fresh Group",
            "url": "https://t.me/combot_test_bot?startgroup=true&admin=delete_messages",
        },
        {
            "group_id": 7,
            "tg_group_id": -1008101,
            "title": "Managed Group",
            "url": "https://t.me/combot_test_bot?startgroup=true&admin=delete_messages",
        },
    ]
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_owner_groups_endpoint_requires_owner(api_client, db_session) -> None:
    group = Group(tg_group_id=-1007991, title="Restricted Owner Group", is_active=True)
    db_session.add(group)
    await db_session.commit()

    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=9091)}
    response = await api_client.get("/webapp/owner/groups", headers=headers)

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_owner_subscriptions_endpoint_requires_owner(api_client) -> None:
    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=9190)}
    response = await api_client.get("/webapp/owner/subscriptions", headers=headers)

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_owner_subscriptions_flow(
    api_client,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
    fake_bot,
) -> None:
    monkeypatch.setenv("BOT_OWNER_IDS", "9199")
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

    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=9199)}

    list_resp = await api_client.get("/webapp/owner/subscriptions", headers=headers)
    assert list_resp.status_code == 200
    payload = list_resp.json()
    assert payload
    assert payload[0]["tg_user_id"] == 2222

    update_resp = await api_client.post(
        f"/webapp/owner/subscriptions/{request.id}",
        headers=headers,
        json={"status": "approved", "response": "Welcome aboard"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["status"] == "approved"
    assert update_resp.json()["response"] == "Welcome aboard"
    assert fake_bot.sent_messages == [(2222, "Your subscription request was approved.\nNote: Welcome aboard")]

    cancel_resp = await api_client.post(
        f"/webapp/owner/subscriptions/{request.id}",
        headers=headers,
        json={"status": "cancelled", "response": "Access removed"},
    )
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"
    assert cancel_resp.json()["response"] == "Access removed"
    assert fake_bot.sent_messages[-1] == (2222, "Your subscription was cancelled.\nNote: Access removed")


@pytest.mark.asyncio
async def test_owner_private_access_gate_flow(
    api_client,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOT_OWNER_IDS", "9198")
    get_settings.cache_clear()
    first = Group(tg_group_id=-1008101, title="Alpha Gate", is_active=True)
    second = Group(tg_group_id=-1008102, title="Beta Gate", is_active=True)
    db_session.add_all([first, second])
    db_session.add(PrivateAccessRequirement(required_group_tg_id=first.tg_group_id))
    await db_session.commit()

    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=9198)}

    list_resp = await api_client.get("/webapp/owner/private-access-gate", headers=headers)
    assert list_resp.status_code == 200
    payload = list_resp.json()
    assert payload["required_group_tg_ids"] == [first.tg_group_id]
    assert [item["title"] for item in payload["candidates"]] == ["Alpha Gate", "Beta Gate"]

    update_resp = await api_client.patch(
        "/webapp/owner/private-access-gate",
        headers=headers,
        json={"required_group_tg_ids": [second.tg_group_id, 12345]},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["required_group_tg_ids"] == [second.tg_group_id]

    rows = (
        await db_session.execute(
            select(PrivateAccessRequirement.required_group_tg_id).order_by(
                PrivateAccessRequirement.required_group_tg_id.asc()
            )
        )
    ).scalars().all()
    assert rows == [second.tg_group_id]


@pytest.mark.asyncio
async def test_owner_groups_and_actions_flow(
    api_client,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
    fake_bot,
) -> None:
    monkeypatch.setenv("BOT_OWNER_IDS", "9092")
    get_settings.cache_clear()
    group = Group(tg_group_id=-1007992, title="Fleet Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=501, role="owner"))
    db_session.add(GroupSetting(group_id=group.id, key="anti_spam", value={"value": True}))
    db_session.add(PluginEnabled(group_id=group.id, plugin_name="anti_links", enabled=True, config={}))
    db_session.add(Warning(group_id=group.id, user_id=77, issued_by=501, reason="spam", count=2))
    db_session.add(ModerationLog(group_id=group.id, action="warn", target_user_id=77, admin_user_id=501, reason="spam", details={}))
    await db_session.commit()

    monkeypatch.setattr("bot.dashboard.api.owner.Bot", lambda token: fake_bot)
    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=9092)}

    stats_resp = await api_client.get("/webapp/owner/stats", headers=headers)
    assert stats_resp.status_code == 200
    assert stats_resp.json()["total_groups"] >= 1

    groups_resp = await api_client.get("/webapp/owner/groups", headers=headers)
    assert groups_resp.status_code == 200
    assert groups_resp.json()[0]["title"] == "Fleet Group"

    detail_resp = await api_client.get(f"/webapp/owner/groups/{group.id}", headers=headers)
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["group"]["title"] == "Fleet Group"
    assert detail["settings"][0]["key"] == "anti_spam"
    assert detail["plugins"][0]["plugin_name"] == "anti_links"

    disable_resp = await api_client.post(f"/webapp/owner/groups/{group.id}/disable", headers=headers)
    assert disable_resp.status_code == 200
    assert disable_resp.json()["group"]["is_active"] is False

    group.is_active = True
    await db_session.commit()

    leave_resp = await api_client.post(f"/webapp/owner/groups/{group.id}/leave", headers=headers)
    assert leave_resp.status_code == 200
    assert leave_resp.json()["status"] == "left"
    assert fake_bot.left_chats == [group.tg_group_id]


@pytest.mark.asyncio
async def test_webapp_agents_flow(api_client, db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_OWNER_IDS", "6666")
    get_settings.cache_clear()

    user = User(tg_user_id=6666, username="user6666")
    db_session.add(user)
    await db_session.flush()

    group = Group(tg_group_id=-1007003, title="Agents API Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=user.id, role="owner"))
    await db_session.commit()

    async def fake_dispatch_agent_job(job_id: int) -> None:
        _ = job_id

    monkeypatch.setattr("bot.dashboard.api.routers.agents.dispatch_agent_job", fake_dispatch_agent_job)

    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=6666), "X-App-Boundary": "agents"}

    link_resp = await api_client.post(
        "/webapp/agents/link",
        headers=headers,
        json={"group_id": group.id, "name": "Sales Bot", "phone_number": "+15550001111", "metadata": {"source": "webapp"}},
    )
    assert link_resp.status_code == 200
    agent_id = link_resp.json()["agent"]["id"]
    assert link_resp.json()["agent"]["external_account_id"] == "Sales Bot"
    assert link_resp.json()["agent"]["phone_number"] == "+15550001111"
    assert link_resp.json()["agent"]["status"] == "pending"
    assert link_resp.json()["agent"]["auth_state"] == "pending_auth"
    assert link_resp.json()["agent"]["metadata"]["display_name"] == "Sales Bot"

    list_resp = await api_client.get(f"/webapp/agents/list?group_id={group.id}", headers=headers)
    assert list_resp.status_code == 200
    assert list_resp.json()[0]["external_account_id"] == "Sales Bot"
    assert list_resp.json()[0]["phone_number"] == "+15550001111"

    duplicate_resp = await api_client.post(
        "/webapp/agents/link",
        headers=headers,
        json={"group_id": group.id, "name": "Backup Bot", "phone_number": "+1 (555) 000-1111"},
    )
    assert duplicate_resp.status_code == 422
    assert duplicate_resp.json()["detail"] == "Phone number is already linked for this subscription"

    invalid_phone_resp = await api_client.post(
        "/webapp/agents/link",
        headers=headers,
        json={"group_id": group.id, "name": "Bad Phone Bot", "phone_number": "555"},
    )
    assert invalid_phone_resp.status_code == 422
    assert "international format" in invalid_phone_resp.json()["detail"]

    stored_agent = (await db_session.execute(select(Agent).where(Agent.id == agent_id))).scalar_one()
    stored_agent.status = "active"
    stored_agent.auth_state = "active"
    stored_agent.session_string = "session:active"
    await db_session.commit()

    job_resp = await api_client.post(
        f"/webapp/agents/{agent_id}/jobs",
        headers=headers,
        json={"job_type": "sync", "job_payload": {"priority": "high"}},
    )
    assert job_resp.status_code == 200

    jobs_resp = await api_client.get(f"/webapp/agents/{agent_id}/jobs", headers=headers)
    assert jobs_resp.status_code == 200
    assert jobs_resp.json()[0]["job_type"] == "sync"

    delete_resp = await api_client.delete(f"/webapp/agents/{agent_id}", headers=headers)
    assert delete_resp.status_code == 200
    assert delete_resp.json()["deleted"] is True


@pytest.mark.asyncio
async def test_webapp_agents_flow_without_group_uses_hidden_workspace(
    api_client,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOT_OWNER_IDS", "7666")
    get_settings.cache_clear()

    user = User(tg_user_id=7666, username="user7666")
    db_session.add(user)
    await db_session.flush()

    async def fake_dispatch_agent_job(job_id: int) -> None:
        _ = job_id

    monkeypatch.setattr("bot.dashboard.api.routers.agents.dispatch_agent_job", fake_dispatch_agent_job)

    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=7666), "X-App-Boundary": "agents"}

    link_resp = await api_client.post(
        "/webapp/agents/link",
        headers=headers,
        json={"name": "Workspace Bot", "phone_number": "+15550002222"},
    )
    assert link_resp.status_code == 200
    agent = link_resp.json()["agent"]
    assert agent["external_account_id"] == "Workspace Bot"
    assert agent["phone_number"] == "+15550002222"

    list_resp = await api_client.get("/webapp/agents/list", headers=headers)
    assert list_resp.status_code == 200
    payload = list_resp.json()
    assert payload[0]["id"] == agent["id"]
    assert payload[0]["group_id"] == agent["group_id"]

    workspace_group = (await db_session.execute(select(Group).where(Group.id == agent["group_id"]))).scalar_one()
    assert workspace_group.title == "Agents Workspace"
    assert workspace_group.is_active is False


@pytest.mark.asyncio
async def test_webapp_group_member_search_uses_admin_member_service(
    api_client,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOT_OWNER_IDS", "6667")
    get_settings.cache_clear()

    user = User(tg_user_id=6667, username="user6667")
    db_session.add(user)
    await db_session.flush()

    group = Group(tg_group_id=-10070031, title="Lookup Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=user.id, role="owner"))
    await db_session.commit()

    captured: dict[str, int | str | None] = {}

    async def fake_search_group_members(self, *, actor_user_id: int, group_id: int, query: str | None = None, limit: int = 25):
        captured.update(
            {
                "actor_user_id": actor_user_id,
                "group_id": group_id,
                "query": query,
                "limit": limit,
            }
        )
        return [
            {
                "user_id": 991100,
                "username": "member_one",
                "full_name": "Member One",
                "role": "member",
            }
        ]

    monkeypatch.setattr(
        "bot.services.admin_group_member_service.AccountGroupMembershipService.search_group_members",
        fake_search_group_members,
    )

    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=6667)}
    response = await api_client.get(f"/api/admin/groups/{group.id}/member-search?q=mem&limit=12", headers=headers)

    assert response.status_code == 200
    assert response.json()[0]["username"] == "member_one"
    assert captured == {
        "actor_user_id": 6667,
        "group_id": group.id,
        "query": "mem",
        "limit": 12,
    }


@pytest.mark.asyncio
async def test_api_admin_member_search_translates_admin_boundary_errors(
    api_client,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOT_OWNER_IDS", "6669")
    get_settings.cache_clear()

    user = User(tg_user_id=6669, username="user6669")
    db_session.add(user)
    await db_session.flush()

    group = Group(tg_group_id=-10070039, title="Lookup Error Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=user.id, role="owner"))
    await db_session.commit()

    async def fake_search_group_members(self, *, actor_user_id: int, group_id: int, query: str | None = None, limit: int = 25):
        _ = (self, actor_user_id, group_id, query, limit)
        raise AdminGroupMemberSearchRateLimitedError(45)

    monkeypatch.setattr(
        "bot.services.admin_group_member_service.AdminGroupMemberService.search_group_members",
        fake_search_group_members,
    )

    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=6669)}
    response = await api_client.get(f"/api/admin/groups/{group.id}/member-search?q=mem&limit=12", headers=headers)

    assert response.status_code == 429
    assert response.json()["detail"] == "Linked account is rate limited. Retry after 45s."


@pytest.mark.asyncio
async def test_webapp_set_member_role_uses_admin_role_service(api_client, db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_OWNER_IDS", "6670")
    get_settings.cache_clear()

    user = User(tg_user_id=6670, username="user6670")
    db_session.add(user)
    await db_session.flush()

    group = Group(tg_group_id=-10070041, title="Role Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=user.id, role="owner"))
    await db_session.commit()

    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=6670)}
    response = await api_client.post(
        f"/api/admin/groups/{group.id}/members/9001/role",
        headers=headers,
        json={"role": "moderator"},
    )

    assert response.status_code == 200
    role_row = (
        await db_session.execute(
            select(GroupAdminRole).where(
                GroupAdminRole.group_id == group.id,
                GroupAdminRole.user_id == 9001,
            )
        )
    ).scalar_one()
    assert role_row.role == "moderator"

    log_row = (
        await db_session.execute(
            select(ModerationLog).where(
                ModerationLog.group_id == group.id,
                ModerationLog.action == "set_admin_role",
            )
        )
    ).scalar_one()
    assert log_row.details["new_role"] == "moderator"
    assert log_row.details["domain"] == "admin"
    assert log_row.details["runtime_event"] == "admin.member_role_updated"
    assert log_row.admin_user_id == 6670


@pytest.mark.asyncio
async def test_internal_runtime_audit_endpoint_returns_replay_shape(api_client, db_session) -> None:
    group = Group(tg_group_id=-10070042, title="Runtime Audit Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    log = ModerationLog(
        group_id=group.id,
        action="destination_notified",
        target_user_id=888,
        admin_user_id=None,
        reason="pricing",
        details={
            "domain": "automation",
            "runtime_event": "automation.notify_destination_requested",
            "runtime_action": "send_runtime_message",
            "source_runtime": "automation.runtime",
            "selected_actions": ["send_runtime_message"],
            "guard_outcomes": [{"decision": "allow", "reason": None, "details": {}}],
            "execution_result": {"chat_id": 123456, "destination_message_id": 1001},
            "compat_schema_version": 1,
        },
    )
    db_session.add(log)
    await db_session.commit()

    response = await api_client.get(f"/groups/{group.id}/runtime-audits")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["runtime_event"] == "automation.notify_destination_requested"
    assert payload[0]["selected_actions"] == ["send_runtime_message"]
    assert payload[0]["execution_result"]["destination_message_id"] == 1001


@pytest.mark.asyncio
async def test_webapp_agent_group_and_member_search(
    api_client,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOT_OWNER_IDS", "6668")
    get_settings.cache_clear()

    user = User(tg_user_id=6668, username="user6668")
    db_session.add(user)
    await db_session.flush()

    group = Group(tg_group_id=-10070032, title="Agent Lookup Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=user.id, role="owner"))
    agent = Agent(
        group_id=group.id,
        phone_number="+10000000001",
        external_account_id="linkedagent-1",
        auth_state="active",
        session_string="session",
        details={"username": "linkedagent"},
    )
    db_session.add(agent)
    await db_session.commit()

    groups_captured: dict[str, int] = {}
    members_captured: dict[str, int | str | None] = {}

    async def fake_list_managed_member_groups(self, *, actor_user_id: int, agent_id: int, query: str | None = None):
        groups_captured.update({"actor_user_id": actor_user_id, "agent_id": agent_id, "query": query})
        return [{"tg_group_id": -1009001, "title": "Remote Group"}]

    member_messages_captured: dict[str, int] = {}

    async def fake_list_scraped_agent_group_members(
        self,
        *,
        actor_user_id: int,
        agent_id: int,
        tg_group_id: int,
        query: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ):
        members_captured.update(
            {
                "actor_user_id": actor_user_id,
                "agent_id": agent_id,
                "tg_group_id": tg_group_id,
                "query": query,
                "page": page,
                "page_size": page_size,
            }
        )
        return {
            "members": [
                {
                    "user_id": 88,
                    "username": "remote_member",
                    "full_name": "Remote Member",
                    "role": "member",
                    "message_count": 4,
                }
            ],
            "total": 1,
            "page": page,
            "page_size": page_size,
        }

    async def fake_list_scraped_agent_group_member_messages(
        self,
        *,
        actor_user_id: int,
        agent_id: int,
        tg_group_id: int,
        user_id: int,
        page: int = 1,
        page_size: int = 25,
    ):
        member_messages_captured.update(
            {
                "actor_user_id": actor_user_id,
                "agent_id": agent_id,
                "tg_group_id": tg_group_id,
                "user_id": user_id,
                "page": page,
                "page_size": page_size,
            }
        )
        return {
            "messages": [
                {
                    "message_id": 51,
                    "text": "hello from remote member",
                    "date": "2026-01-01T10:00:00+00:00",
                    "message_type": "text",
                    "username": "remote_member",
                    "full_name": "Remote Member",
                }
            ],
            "total": 1,
            "page": page,
            "page_size": page_size,
        }

    monkeypatch.setattr(
        "bot.agents.account_group_membership_service.AccountGroupMembershipService.list_managed_member_groups",
        fake_list_managed_member_groups,
    )
    monkeypatch.setattr(
        "bot.agents.account_group_membership_service.AccountGroupMembershipService.list_scraped_agent_group_members",
        fake_list_scraped_agent_group_members,
    )
    monkeypatch.setattr(
        "bot.agents.account_group_membership_service.AccountGroupMembershipService.list_scraped_agent_group_member_messages",
        fake_list_scraped_agent_group_member_messages,
    )

    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=6668), "X-App-Boundary": "agents"}
    groups_response = await api_client.get(f"/webapp/agents/{agent.id}/groups", headers=headers)
    members_response = await api_client.get(
        f"/webapp/agents/{agent.id}/member-search?tg_group_id=-1009001&q=rem&limit=15",
        headers=headers,
    )
    paged_members_response = await api_client.get(
        f"/webapp/agents/{agent.id}/groups/-1009001/members?q=rem&page=2&page_size=5",
        headers=headers,
    )
    member_messages_response = await api_client.get(
        f"/webapp/agents/{agent.id}/groups/-1009001/members/88/messages?page=3&page_size=20",
        headers=headers,
    )

    assert groups_response.status_code == 200
    assert groups_response.json() == [{"tg_group_id": -1009001, "title": "Remote Group"}]
    assert groups_captured == {"actor_user_id": 6668, "agent_id": agent.id, "query": None}

    assert members_response.status_code == 200
    assert members_response.json()[0]["username"] == "remote_member"
    assert paged_members_response.status_code == 200
    assert paged_members_response.json()["members"][0]["username"] == "remote_member"
    assert paged_members_response.json()["members"][0]["message_count"] == 4
    assert member_messages_response.status_code == 200
    assert member_messages_response.json()["messages"][0]["message_id"] == 51
    assert members_captured == {
        "actor_user_id": 6668,
        "agent_id": agent.id,
        "tg_group_id": -1009001,
        "query": "rem",
        "page": 2,
        "page_size": 5,
    }
    assert member_messages_captured == {
        "actor_user_id": 6668,
        "agent_id": agent.id,
        "tg_group_id": -1009001,
        "user_id": 88,
        "page": 3,
        "page_size": 20,
    }


@pytest.mark.asyncio
async def test_webapp_agent_group_scrape_members(
    api_client,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOT_OWNER_IDS", "6672")
    get_settings.cache_clear()

    user = User(tg_user_id=6672, username="user6672")
    db_session.add(user)
    await db_session.flush()

    group = Group(tg_group_id=-10070038, title="Agent Scrape Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=user.id, role="owner"))
    agent = Agent(
        group_id=group.id,
        phone_number="+10000000009",
        external_account_id="linkedagent-scrape",
        auth_state="active",
        session_string="session",
        details={"username": "linkedagent"},
    )
    db_session.add(agent)
    await db_session.commit()

    captured: dict[str, int | None] = {}

    async def fake_scrape_agent_member_group(
        self,
        *,
        actor_user_id: int,
        agent_id: int,
        tg_group_id: int,
        limit: int = 500,
        message_limit: int | None = None,
        max_age_days: int | None = None,
    ):
        captured.update(
            {
                "actor_user_id": actor_user_id,
                "agent_id": agent_id,
                "tg_group_id": tg_group_id,
                "limit": limit,
                "message_limit": message_limit,
                "max_age_days": max_age_days,
            }
        )
        return {"success_count": 12, "error_count": 0, "total_scraped": 12}

    monkeypatch.setattr(
        "bot.agents.account_group_membership_service.AccountGroupMembershipService.scrape_agent_member_group",
        fake_scrape_agent_member_group,
    )

    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=6672), "X-App-Boundary": "agents"}
    response = await api_client.post(
        f"/webapp/agents/{agent.id}/groups/-1009008/scrape-members?limit=50000&message_limit=45000&max_age_days=14",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["success_count"] == 12
    assert captured == {
        "actor_user_id": 6672,
        "agent_id": agent.id,
        "tg_group_id": -1009008,
        "limit": 50000,
        "message_limit": 45000,
        "max_age_days": 14,
    }


@pytest.mark.asyncio
async def test_webapp_agent_notifications_flow(api_client, db_session) -> None:
    group = Group(tg_group_id=-10070039, title="Agent Notification Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=6673, role="owner"))
    agent = Agent(
        group_id=group.id,
        phone_number="+10000000010",
        external_account_id="linkedagent-notify",
        auth_state="active",
        session_string="session",
        details={"username": "linkedagentnotify"},
    )
    db_session.add(agent)
    await db_session.flush()
    db_session.add_all(
        [
            AgentNotification(
                agent_id=agent.id,
                group_id=group.id,
                kind="scrape_completed",
                title="Scrape finished",
                body="First notification",
                payload={},
                is_seen=False,
            ),
            AgentNotification(
                agent_id=agent.id,
                group_id=group.id,
                kind="scrape_completed",
                title="Scrape finished again",
                body="Second notification",
                payload={},
                is_seen=True,
            ),
        ]
    )
    await db_session.commit()

    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=6673), "X-App-Boundary": "agents"}
    list_response = await api_client.get(f"/webapp/agents/{agent.id}/notifications?limit=20", headers=headers)

    assert list_response.status_code == 200
    assert list_response.json()["unseen_count"] == 1
    assert len(list_response.json()["items"]) == 2

    mark_seen_response = await api_client.post(f"/webapp/agents/{agent.id}/notifications/mark-seen", headers=headers)
    assert mark_seen_response.status_code == 200
    assert mark_seen_response.json()["updated"] == 1

    refreshed = await api_client.get(f"/webapp/agents/{agent.id}/notifications?limit=20", headers=headers)
    assert refreshed.status_code == 200
    assert refreshed.json()["unseen_count"] == 0


@pytest.mark.asyncio
async def test_webapp_group_overview_includes_scraped_counts(api_client, db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_OWNER_IDS", "6680")
    get_settings.cache_clear()

    user = User(tg_user_id=6680, username="user6680")
    db_session.add(user)
    await db_session.flush()

    group = Group(tg_group_id=-10070123, title="Overview Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=user.id, role="owner"))
    scraped_group = ScrapedGroup(tg_group_id=group.tg_group_id, title=group.title, member_count=2)
    db_session.add(scraped_group)
    await db_session.flush()
    db_session.add_all(
        [
            ScrapedMember(scraped_group_id=scraped_group.id, tg_group_id=group.tg_group_id, tg_user_id=1, full_name="One"),
            ScrapedMember(scraped_group_id=scraped_group.id, tg_group_id=group.tg_group_id, tg_user_id=2, full_name="Two"),
            ScrapedMember(scraped_group_id=scraped_group.id, tg_group_id=group.tg_group_id, tg_user_id=3, full_name="Three"),
            ScrapedMessage(scraped_group_id=scraped_group.id, tg_group_id=group.tg_group_id, message_id=10),
            ScrapedMessage(scraped_group_id=scraped_group.id, tg_group_id=group.tg_group_id, message_id=11),
        ]
    )
    await db_session.commit()

    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=6680)}
    response = await api_client.get(f"/webapp/groups/{group.id}/overview", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["stats"]["members_count"] == 3
    assert payload["stats"]["messages_count"] == 2
    assert payload["stats"]["member_growth"]["tracked_admin_accounts"] == 3


@pytest.mark.asyncio
async def test_webapp_agent_job_dispatches(
    api_client,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOT_OWNER_IDS", "6669")
    get_settings.cache_clear()

    user = User(tg_user_id=6669, username="user6669")
    db_session.add(user)
    await db_session.flush()

    group = Group(tg_group_id=-10070033, title="Dispatch Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=user.id, role="owner"))
    agent = Agent(
        group_id=group.id,
        telegram_user_id=6669,
        external_account_id="agent-9999",
        auth_state="active",
        session_string="session",
    )
    db_session.add(agent)
    await db_session.commit()

    dispatch_called: list[int] = []

    async def fake_dispatch_agent_job(job_id: int) -> None:
        dispatch_called.append(job_id)

    monkeypatch.setattr("bot.dashboard.api.routers.agents.dispatch_agent_job", fake_dispatch_agent_job)

    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=6669), "X-App-Boundary": "agents"}
    response = await api_client.post(
        f"/webapp/agents/{agent.id}/jobs",
        json={
            "job_type": "group_member_broadcast",
            "job_payload": {"source_group_id": "-1000001", "message": "Hi", "threshold": 1, "interval_seconds": 0},
        },
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["job"]["status"] == "pending"
    assert dispatch_called, "dispatch_agent_job should be invoked after job creation"



@pytest.mark.asyncio
async def test_webapp_scheduled_messages_flow(api_client, db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    group = Group(tg_group_id=-1007004, title="Scheduled Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=7770, role="owner"))
    await db_session.commit()

    scheduled_calls: list[tuple[int, int, str]] = []
    monkeypatch.setattr(
        "bot.dashboard.api.routers.admin_automation.schedule_scheduled_announcement",
        lambda *, delay_seconds, group_id, entry_id: scheduled_calls.append((delay_seconds, group_id, entry_id)),
    )
    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=7770)}

    create_resp = await api_client.post(
        f"/webapp/groups/{group.id}/scheduled-messages",
        headers=headers,
        json={"text": "Deploy reminder", "schedule": "+10m", "delete_after_seconds": 45},
    )
    assert create_resp.status_code == 200
    entry_id = create_resp.json()["scheduled_message"]["id"]
    assert scheduled_calls

    api_list_resp = await api_client.get(f"/api/admin/groups/{group.id}/scheduled-messages", headers=headers)
    assert api_list_resp.status_code == 200
    assert api_list_resp.json()[0]["text"] == "Deploy reminder"

    list_resp = await api_client.get(f"/webapp/groups/{group.id}/scheduled-messages", headers=headers)
    assert list_resp.status_code == 200
    assert list_resp.json()[0]["text"] == "Deploy reminder"
    assert list_resp.json()[0]["delete_after_seconds"] == 45

    update_resp = await api_client.patch(
        f"/webapp/groups/{group.id}/scheduled-messages/{entry_id}",
        headers=headers,
        json={"text": "Updated deploy reminder", "schedule": "*/15 * * * *", "delete_after_seconds": 90},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["scheduled_message"]["cron"] == "*/15 * * * *"
    assert update_resp.json()["scheduled_message"]["delete_after_seconds"] == 90

    delete_resp = await api_client.delete(f"/webapp/groups/{group.id}/scheduled-messages/{entry_id}", headers=headers)
    assert delete_resp.status_code == 200
    assert delete_resp.json()["deleted"] is True


@pytest.mark.asyncio
async def test_webapp_moderation_actions_flow(api_client, db_session, monkeypatch: pytest.MonkeyPatch, fake_bot) -> None:
    monkeypatch.setenv("BOT_OWNER_IDS", "8881")
    get_settings.cache_clear()

    user = User(tg_user_id=8881, username="user8881")
    db_session.add(user)
    await db_session.flush()

    group = Group(tg_group_id=-1007005, title="Moderation Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=user.id, role="owner"))
    db_session.add(Warning(group_id=group.id, user_id=555, issued_by=8881, reason="link", count=1))
    await db_session.commit()

    monkeypatch.setattr("bot.core.runtime.moderation.Bot", lambda token: fake_bot)
    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=8881)}

    approve_resp = await api_client.post(
        f"/webapp/groups/{group.id}/moderation/actions",
        headers=headers,
        json={"user_id": 555, "action": "approve", "reason": "false positive"},
    )
    assert approve_resp.status_code == 200

    warn_resp = await api_client.post(
        f"/webapp/groups/{group.id}/moderation/actions",
        headers=headers,
        json={"user_id": 555, "action": "warn", "reason": "link spam", "count": 1},
    )
    assert warn_resp.status_code == 200

    mute_resp = await api_client.post(
        f"/webapp/groups/{group.id}/moderation/actions",
        headers=headers,
        json={"user_id": 555, "action": "mute", "reason": "repeat spam"},
    )
    assert mute_resp.status_code == 200

    ban_resp = await api_client.post(
        f"/webapp/groups/{group.id}/moderation/actions",
        headers=headers,
        json={"user_id": 555, "action": "ban", "reason": "escalated"},
    )
    assert ban_resp.status_code == 200

    warnings_resp = await api_client.get(f"/webapp/groups/{group.id}/moderation/warnings", headers=headers)
    assert warnings_resp.status_code == 200
    assert warnings_resp.json()[0]["count"] == 1
    assert fake_bot.muted_members == [(group.tg_group_id, 555)]
    assert fake_bot.banned_members == [(group.tg_group_id, 555)]

    logs = (
        await db_session.execute(ModerationLog.__table__.select().where(ModerationLog.group_id == group.id))
    ).all()
    actions = {row.action for row in logs}
    assert {"approve_warning", "warn", "mute_user", "ban_user"}.issubset(actions)


@pytest.mark.asyncio
async def test_webapp_moderation_actions_enforce_permissions(api_client, db_session, monkeypatch: pytest.MonkeyPatch, fake_bot) -> None:
    user = User(tg_user_id=8882, username="user8882")
    db_session.add(user)
    await db_session.flush()

    from bot.db.models.subscription import SubscriptionRequest
    db_session.add(SubscriptionRequest(tg_user_id=8882, status="approved", plan="pro"))

    group = Group(tg_group_id=-1007006, title="Permission Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=user.id, role="moderator"))
    await db_session.commit()

    monkeypatch.setattr("bot.core.runtime.moderation.Bot", lambda token: fake_bot)
    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=8882)}

    warn_resp = await api_client.post(
        f"/webapp/groups/{group.id}/moderation/actions",
        headers=headers,
        json={"user_id": 777, "action": "warn", "reason": "spam"},
    )
    assert warn_resp.status_code == 200

    ban_resp = await api_client.post(
        f"/webapp/groups/{group.id}/moderation/actions",
        headers=headers,
        json={"user_id": 777, "action": "ban", "reason": "spam"},
    )
    assert ban_resp.status_code == 403


@pytest.mark.asyncio
async def test_webapp_set_member_role_accepts_json_body(api_client, db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_OWNER_IDS", "8883")
    get_settings.cache_clear()

    user = User(tg_user_id=8883, username="user8883")
    db_session.add(user)
    await db_session.flush()

    group = Group(tg_group_id=-1007007, title="Role Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=user.id, role="owner"))
    await db_session.commit()

    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=8883)}
    response = await api_client.post(
        f"/webapp/groups/{group.id}/members/777/role",
        headers=headers,
        json={"role": "admin"},
    )

    assert response.status_code == 200
    updated_role = (
        await db_session.execute(
            select(GroupAdminRole).where(GroupAdminRole.group_id == group.id, GroupAdminRole.user_id == 777)
        )
    ).scalar_one()
    assert updated_role.role == "admin"
