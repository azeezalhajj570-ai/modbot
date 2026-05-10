from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from bot.dashboard.api.main import app
from bot.db.models import Agent, Group, GroupAdminRole, ModerationLog, ScrapedGroup


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
async def test_webapp_group_tasks_flow(api_client, db_session) -> None:
    group = Group(tg_group_id=-1007101, title="Tasks Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=7777, role="owner"))
    agent = Agent(
        group_id=group.id,
        telegram_user_id=90001,
        external_account_id="ops-agent",
        status="active",
        auth_state="active",
        session_string="session",
        details={},
    )
    db_session.add(agent)
    await db_session.commit()

    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=7777)}

    catalog_resp = await api_client.get("/webapp/tasks/catalog", headers=headers)
    assert catalog_resp.status_code == 200
    assert catalog_resp.json()[0]["key"] == "reply_message"
    assert catalog_resp.json()[0]["planner"] == "rules"
    assert catalog_resp.json()[0]["task_trigger"] == {"event_name": "message.received"}
    assert catalog_resp.json()[0]["action_template"]["kind"] == "send_runtime_message"

    api_catalog_resp = await api_client.get("/api/admin/tasks/catalog", headers=headers)
    assert api_catalog_resp.status_code == 200
    assert api_catalog_resp.json()[0]["key"] == "reply_message"

    create_resp = await api_client.post(
        f"/webapp/groups/{group.id}/tasks",
        headers=headers,
        json={
            "task_key": "reply_message",
            "executor_type": "agent",
            "agent_id": agent.id,
            "conditions": {"text_contains": "support"},
            "config": {"message_template": "Agent will help shortly"},
        },
    )
    assert create_resp.status_code == 200
    assignment_id = create_resp.json()["assignment"]["assignment_id"]

    update_resp = await api_client.patch(
        f"/webapp/groups/{group.id}/tasks/{assignment_id}",
        headers=headers,
        json={
            "task_key": "reply_message",
            "executor_type": "agent",
            "agent_id": agent.id,
            "conditions": {"text_contains": "billing"},
            "config": {"message_template": "Updated task reply"},
        },
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["assignment"]["conditions"]["text_contains"] == "billing"

    list_resp = await api_client.get(f"/webapp/groups/{group.id}/tasks", headers=headers)
    assert list_resp.status_code == 200
    assert list_resp.json()[0]["assignment_id"] == assignment_id
    assert list_resp.json()[0]["config"]["message_template"] == "Updated task reply"
    assert list_resp.json()[0]["condition_rules"] == [
        {"key": "text_contains", "operator": "contains", "value": "billing"}
    ]

    delete_resp = await api_client.delete(f"/webapp/groups/{group.id}/tasks/{assignment_id}", headers=headers)
    assert delete_resp.status_code == 200
    assert delete_resp.json()["deleted"] is True

    api_list_resp = await api_client.get(f"/api/admin/groups/{group.id}/tasks", headers=headers)
    assert api_list_resp.status_code == 200
    assert api_list_resp.json() == []


@pytest.mark.asyncio
async def test_webapp_group_task_accepts_agent_visible_group(api_client, db_session) -> None:
    group = Group(tg_group_id=-1007105, title="Agent Home Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=7781, role="owner"))
    agent = Agent(
        group_id=group.id,
        telegram_user_id=90002,
        external_account_id="visible-agent",
        status="active",
        auth_state="active",
        session_string="session",
        details={},
    )
    db_session.add(agent)
    await db_session.flush()
    visible_group = ScrapedGroup(
        tg_group_id=-1009876501,
        last_agent_id=agent.id,
        title="Visible Remote Group",
        group_type="supergroup",
    )
    db_session.add(visible_group)
    await db_session.commit()

    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=7781)}
    create_resp = await api_client.post(
        f"/webapp/groups/{group.id}/tasks",
        headers=headers,
        json={
            "task_key": "reply_message",
            "executor_type": "agent",
            "agent_id": agent.id,
            "conditions": {"text_contains": "support"},
            "config": {"message_template": "Visible group reply"},
            "group_tg_ids": [visible_group.tg_group_id],
            "group_titles": [visible_group.title],
        },
    )

    assert create_resp.status_code == 200
    assert create_resp.json()["assignment"]["group_tg_ids"] == [visible_group.tg_group_id]
    assert create_resp.json()["assignment"]["group_titles"] == [visible_group.title]


@pytest.mark.asyncio
async def test_webapp_group_task_delete_survives_notification_failure(
    api_client,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group = Group(tg_group_id=-1007106, title="Notification Failure Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=7782, role="owner"))
    agent = Agent(
        group_id=group.id,
        telegram_user_id=90003,
        external_account_id="notify-failure-agent",
        status="active",
        auth_state="active",
        session_string="session",
        details={},
    )
    db_session.add(agent)
    await db_session.commit()

    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=7782)}
    create_resp = await api_client.post(
        f"/webapp/groups/{group.id}/tasks",
        headers=headers,
        json={
            "task_key": "reply_message",
            "executor_type": "agent",
            "agent_id": agent.id,
            "conditions": {"text_contains": "delete"},
            "config": {"message_template": "Task reply"},
        },
    )
    assert create_resp.status_code == 200
    assignment_id = create_resp.json()["assignment"]["assignment_id"]

    async def fail_create_notification(self, **kwargs):
        _ = self, kwargs
        raise RuntimeError("notification store unavailable")

    monkeypatch.setattr(
        "bot.agents.agent_notification_service.AgentNotificationService.create_notification",
        fail_create_notification,
    )

    delete_resp = await api_client.delete(f"/webapp/groups/{group.id}/tasks/{assignment_id}", headers=headers)
    assert delete_resp.status_code == 200
    assert delete_resp.json()["deleted"] is True

    list_resp = await api_client.get(f"/webapp/groups/{group.id}/tasks", headers=headers)
    assert list_resp.status_code == 200
    assert list_resp.json() == []


@pytest.mark.asyncio
async def test_webapp_notify_destination_task_flow(api_client, db_session) -> None:
    group = Group(tg_group_id=-1007104, title="Notify Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=7780, role="owner"))
    await db_session.commit()

    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=7780)}
    create_resp = await api_client.post(
        f"/webapp/groups/{group.id}/tasks",
        headers=headers,
        json={
            "task_key": "notify_destination",
            "executor_type": "bot",
            "conditions": {"text_contains": "urgent"},
            "config": {
                "message_template": "Notify: {text}",
                "destination": "123456",
                "delivery_mode": "text_and_forward",
                "delete_after_seconds": 60,
            },
        },
    )
    assert create_resp.status_code == 200
    assert create_resp.json()["assignment"]["config"]["destination"] == "123456"
    assert create_resp.json()["assignment"]["config"]["delivery_mode"] == "text_and_forward"


@pytest.mark.asyncio
async def test_webapp_group_leads_returns_persisted_leads(api_client, db_session) -> None:
    group = Group(tg_group_id=-1007102, title="Leads Group", is_active=True)
    db_session.add(group)
    await db_session.flush()
    db_session.add(GroupAdminRole(group_id=group.id, user_id=7778, role="owner"))
    db_session.add(
        ModerationLog(
            group_id=group.id,
            action="lead_captured",
            target_user_id=91,
            admin_user_id=None,
            reason="sales",
            details={"lead_label": "sales", "message_text": "Need pricing"},
        )
    )
    await db_session.commit()

    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=7778)}
    leads_resp = await api_client.get(f"/webapp/groups/{group.id}/leads", headers=headers)

    assert leads_resp.status_code == 200
    assert leads_resp.json()[0]["label"] == "sales"
    assert leads_resp.json()[0]["message_text"] == "Need pricing"


@pytest.mark.asyncio
async def test_webapp_group_tasks_requires_group_admin(api_client, db_session) -> None:
    group = Group(tg_group_id=-1007103, title="Restricted Tasks Group", is_active=True)
    db_session.add(group)
    await db_session.commit()

    headers = {"X-Telegram-Init-Data": _webapp_init_data(user_id=8888)}

    list_resp = await api_client.get(f"/webapp/groups/{group.id}/tasks", headers=headers)
    assert list_resp.status_code == 403

    delete_resp = await api_client.delete(f"/webapp/groups/{group.id}/tasks/missing-task", headers=headers)
    assert delete_resp.status_code == 403
