from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient, MockTransport, Request, Response

from bot.config import get_settings
from bot.dashboard.api.main import app
from bot.services.evolution_service import EvolutionSettings, EvolutionWhatsAppService


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


async def _register_and_authenticate(
    api_client: AsyncClient,
    *,
    name: str = "Demo Owner",
    email: str = "owner@example.com",
) -> dict[str, str]:
    register = await api_client.post(
        "/api/auth/register",
        json={"name": name, "email": email, "password": "secret123"},
    )
    assert register.status_code == 200, register.text
    access_token = register.json()["access_token"]
    return {"Authorization": f"Bearer {access_token}"}


async def _set_business_profile(api_client: AsyncClient, headers: dict[str, str], payload: dict) -> None:
    response = await api_client.patch("/api/tenants/current/business-profile", headers=headers, json=payload)
    assert response.status_code == 200, response.text


async def _update_automation_by_slug(
    api_client: AsyncClient,
    headers: dict[str, str],
    *,
    slug: str,
    patch: dict,
) -> None:
    response = await api_client.get("/api/automations", headers=headers)
    assert response.status_code == 200, response.text
    automation = next(item for item in response.json()["automations"] if item["slug"] == slug)
    updated = await api_client.patch(f"/api/automations/{automation['id']}", headers=headers, json=patch)
    assert updated.status_code == 200, updated.text


async def _get_conversation_detail(api_client: AsyncClient, headers: dict[str, str], conversation_id: str) -> dict:
    response = await api_client.get(f"/api/conversations/{conversation_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def _get_notification_settings(api_client: AsyncClient, headers: dict[str, str]) -> dict:
    response = await api_client.get("/api/notification-settings", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["settings"]


def _install_evolution_service(
    monkeypatch: pytest.MonkeyPatch,
    handler,
    *,
    webhook_secret: str | None = None,
) -> list[tuple[str, str, dict | None]]:
    requests: list[tuple[str, str, dict | None]] = []

    def transport_handler(request: Request) -> Response:
        body = None
        if request.content:
            body = json.loads(request.content.decode("utf-8"))
        requests.append((request.method, request.url.path, body))
        return handler(request, body)

    service = EvolutionWhatsAppService(
        EvolutionSettings(
            enabled=True,
            api_base_url="https://evolution.test",
            api_key="server-side-secret",
            webhook_base_url="https://preview.example.com",
            webhook_secret=webhook_secret,
        ),
        transport=MockTransport(transport_handler),
    )
    monkeypatch.setattr(
        EvolutionWhatsAppService,
        "from_env",
        classmethod(lambda cls: service),
    )
    return requests


@pytest.mark.asyncio
async def test_register_connect_simulate_and_read_conversations(api_client) -> None:
    headers = await _register_and_authenticate(api_client)
    await _set_business_profile(
        api_client,
        headers,
        {
            "businessName": "North Clinic",
            "category": "clinic",
            "services": [{"name": "Teeth Whitening", "priceFrom": "$120"}],
            "openingHours": "Mon-Fri 9am-5pm",
            "location": "Downtown",
            "bookingLink": "https://clinic.example.com/book",
            "escalationContact": "+15550009999",
            "faqs": [],
            "forbiddenClaims": ["same-day guaranteed appointment"],
        },
    )

    tenant = await api_client.get("/api/tenants/current", headers=headers)
    assert tenant.status_code == 200
    assert tenant.json()["name"] == "Demo Owner"

    connect = await api_client.post("/api/channels/whatsapp/connect", headers=headers)
    assert connect.status_code == 200
    channel_id = connect.json()["channel"]["id"]
    assert connect.json()["qrCode"].startswith("data:image/svg+xml;base64,")

    notification_settings = await api_client.patch(
        "/api/notification-settings",
        headers=headers,
        json={
            "notifyOnNewLead": True,
            "notifyOnNeedsHuman": True,
            "dailySummaryEnabled": False,
            "notificationChannel": "none",
            "notificationTarget": None,
            "quietHours": None,
        },
    )
    assert notification_settings.status_code == 200, notification_settings.text
    assert notification_settings.json()["settings"]["notificationChannel"] == "none"

    test_notification = await api_client.post("/api/notifications/test", headers=headers)
    assert test_notification.status_code == 200, test_notification.text
    assert test_notification.json()["notification"]["type"] == "test"
    assert test_notification.json()["notification"]["status"] == "skipped"

    simulated = await api_client.post(
        "/api/dev/simulate-whatsapp-message",
        headers=headers,
        json={
            "text": "Hi, I want to book an appointment for teeth whitening. What is the price?",
            "contactName": "Mia Prospect",
            "phone": "+15551234567",
        },
    )
    assert simulated.status_code == 200, simulated.text

    conversations = await api_client.get("/api/conversations", headers=headers)
    assert conversations.status_code == 200
    payload = conversations.json()["conversations"]
    assert len(payload) == 1
    conversation = payload[0]
    assert conversation["contactName"] == "Mia Prospect"
    assert conversation["contactPhone"] == "+15551234567"
    assert conversation["status"] == "ai_active"
    assert conversation["latestMessage"] == "Hi, I want to book an appointment for teeth whitening. What is the price?"

    detail = await api_client.get(f"/api/conversations/{conversation['id']}", headers=headers)
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["conversation"]["id"] == conversation["id"]
    assert any(message["direction"] == "inbound" for message in detail_payload["messages"])
    assert any(message["senderType"] == "ai" for message in detail_payload["messages"])
    assert any(message["senderType"] == "ai" and message["status"] == "draft" for message in detail_payload["messages"])

    leads = await api_client.get("/api/leads", headers=headers)
    assert leads.status_code == 200
    leads_payload = leads.json()["leads"]
    assert len(leads_payload) == 1
    assert leads_payload[0]["status"] == "new"
    assert leads_payload[0]["source"] == "whatsapp"
    assert leads_payload[0]["conversationId"] == conversation["id"]

    analytics = await api_client.get("/api/analytics/overview", headers=headers)
    assert analytics.status_code == 200
    assert analytics.json()["newLeadsToday"] == 1
    assert analytics.json()["pendingNotifications"] == 0
    assert analytics.json()["readiness"]["hasBusinessProfile"] is True
    assert analytics.json()["readiness"]["hasConnectedWhatsApp"] is True
    assert analytics.json()["readiness"]["hasNotificationSettings"] is True

    notifications = await api_client.get("/api/notifications", headers=headers)
    assert notifications.status_code == 200
    events = notifications.json()["notifications"]
    assert any(event["type"] == "test" for event in events)
    assert any(event["type"] == "new_lead" for event in events)

    status = await api_client.get(f"/api/channels/{channel_id}/status", headers=headers)
    assert status.status_code == 200
    assert status.json()["status"] == "connected"


@pytest.mark.asyncio
async def test_telegram_auth_returns_user_and_tenant(api_client) -> None:
    response = await api_client.post(
        "/api/auth/telegram",
        json={"initData": _webapp_init_data(user_id=4545)},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["access_token"]
    assert payload["user"]["telegramId"] == 4545
    assert payload["tenant"]["name"] == "Test"

    me = await api_client.get(
        "/api/me",
        headers={"Authorization": f"Bearer {payload['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["telegramUsername"] == "user4545"


@pytest.mark.asyncio
async def test_default_notification_settings_are_created_and_can_be_patched(api_client) -> None:
    headers = await _register_and_authenticate(api_client, name="Notify Owner", email="notify-owner@example.com")
    settings = await _get_notification_settings(api_client, headers)
    assert settings["notificationChannel"] == "none"
    assert settings["notifyOnNewLead"] is True

    updated = await api_client.patch(
        "/api/notification-settings",
        headers=headers,
        json={
            "notifyOnNewLead": False,
            "notifyOnNeedsHuman": True,
            "dailySummaryEnabled": True,
            "notificationChannel": "none",
            "notificationTarget": None,
            "quietHours": {"start": "22:00", "end": "07:00"},
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["settings"]["dailySummaryEnabled"] is True
    assert updated.json()["settings"]["quietHours"]["start"] == "22:00"


@pytest.mark.asyncio
async def test_invalid_webhook_target_is_rejected(api_client) -> None:
    headers = await _register_and_authenticate(api_client, name="Invalid Webhook", email="invalid-webhook@example.com")
    updated = await api_client.patch(
        "/api/notification-settings",
        headers=headers,
        json={
            "notificationChannel": "webhook",
            "notificationTarget": "not-a-url",
        },
    )
    assert updated.status_code == 400


@pytest.mark.asyncio
async def test_evolution_webhook_can_mark_conversation_for_handoff(api_client) -> None:
    headers = await _register_and_authenticate(api_client, name="Ops Owner", email="ops@example.com")

    connect = await api_client.post("/api/channels/whatsapp/connect", headers=headers)
    channel_id = connect.json()["channel"]["id"]

    webhook = await api_client.post(
        f"/api/webhooks/evolution/{channel_id}",
        json={
            "data": {
                "pushName": "Call Back Lead",
                "message": {
                    "key": {"remoteJid": "15554443333@s.whatsapp.net", "id": "msg-1"},
                    "conversation": "Can a human agent call me?",
                },
            }
        },
    )
    assert webhook.status_code == 200, webhook.text

    conversations = await api_client.get("/api/conversations", headers=headers)
    payload = conversations.json()["conversations"]
    assert len(payload) == 1
    assert payload[0]["status"] == "needs_human"

    detail = await api_client.get(f"/api/conversations/{payload[0]['id']}", headers=headers)
    assert detail.status_code == 200
    assert not any(message["senderType"] == "ai" for message in detail.json()["messages"])

    notifications = await api_client.get("/api/notifications", headers=headers)
    assert notifications.status_code == 200
    assert any(event["type"] == "needs_human" for event in notifications.json()["notifications"])


@pytest.mark.asyncio
async def test_evolution_enabled_channel_connect_status_refresh_send_and_disconnect(api_client, monkeypatch) -> None:
    def handler(request: Request, body: dict | None) -> Response:
        if request.method == "POST" and request.url.path == "/instance/create":
            assert body == {
                "instanceName": "wa_t1_c1",
                "integration": "WHATSAPP-BAILEYS",
                "qrcode": True,
                "number": "",
                "displayName": "WhatsApp Primary",
            }
            return Response(200, json={"instance": {"instanceName": "wa_t1_c1"}, "state": "connecting"})
        if request.method == "POST" and request.url.path == "/webhook/set/wa_t1_c1":
            assert body is not None
            assert body["url"] == "https://preview.example.com/api/webhooks/evolution/1"
            return Response(200, json={"success": True})
        if request.method == "GET" and request.url.path == "/instance/connectionState/wa_t1_c1":
            return Response(200, json={"state": "open"})
        if request.method == "GET" and request.url.path == "/instance/qrcode/wa_t1_c1":
            return Response(200, json={"base64": "cXItYmFzZTY0"})
        if request.method == "GET" and request.url.path == "/instance/connect/wa_t1_c1":
            return Response(200, json={"ok": True})
        if request.method == "POST" and request.url.path == "/message/sendText/wa_t1_c1":
            assert body == {"number": "15551234567", "text": "Manual follow-up from an agent"}
            return Response(200, json={"key": {"id": "outbound-1"}})
        if request.method == "DELETE" and request.url.path in {"/instance/logout/wa_t1_c1", "/instance/delete/wa_t1_c1"}:
            return Response(200, json={"ok": True})
        raise AssertionError(f"Unexpected Evolution request: {request.method} {request.url.path}")

    requests = _install_evolution_service(monkeypatch, handler)
    headers = await _register_and_authenticate(api_client, name="Evolution Owner", email="evolution@example.com")

    connect = await api_client.post("/api/channels/whatsapp/connect", headers=headers)
    assert connect.status_code == 200, connect.text
    connect_payload = connect.json()
    assert connect_payload["channel"]["status"] == "connected"
    assert connect_payload["qrCode"] == "data:image/png;base64,cXItYmFzZTY0"
    assert "credentialsEncrypted" not in connect_payload["channel"]
    assert "externalAccountId" not in connect_payload["channel"]

    channels = await api_client.get("/api/channels", headers=headers)
    assert channels.status_code == 200
    assert channels.json()["channels"][0]["status"] == "connected"
    assert "credentialsEncrypted" not in channels.json()["channels"][0]

    simulated = await api_client.post(
        "/api/dev/simulate-whatsapp-message",
        headers=headers,
        json={"text": "Hello there", "contactName": "Ava Contact", "phone": "+15551234567"},
    )
    assert simulated.status_code == 200
    conversation_id = simulated.json()["conversationId"]

    sent = await api_client.post(
        f"/api/conversations/{conversation_id}/send-message",
        headers=headers,
        json={"text": "Manual follow-up from an agent"},
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["senderType"] == "human"
    assert sent.json()["status"] == "sent"

    detail = await api_client.get(f"/api/conversations/{conversation_id}", headers=headers)
    assert detail.status_code == 200
    assert any(message["senderType"] == "human" and message["direction"] == "outbound" for message in detail.json()["messages"])

    status = await api_client.get("/api/channels/1/status", headers=headers)
    assert status.status_code == 200
    assert status.json()["status"] == "connected"

    refreshed = await api_client.post("/api/channels/1/refresh-qr", headers=headers)
    assert refreshed.status_code == 200
    assert refreshed.json()["qrCode"] == "data:image/png;base64,cXItYmFzZTY0"

    disconnected = await api_client.post("/api/channels/whatsapp/disconnect", headers=headers)
    assert disconnected.status_code == 200
    assert disconnected.json() == {"ok": True}

    assert ("POST", "/instance/create", {"instanceName": "wa_t1_c1", "integration": "WHATSAPP-BAILEYS", "qrcode": True, "number": "", "displayName": "WhatsApp Primary"}) in requests
    assert any(method == "POST" and path == "/message/sendText/wa_t1_c1" for method, path, _ in requests)
    assert any(method == "DELETE" and path == "/instance/logout/wa_t1_c1" for method, path, _ in requests)


@pytest.mark.asyncio
async def test_ai_receptionist_autosend_uses_evolution_and_marks_message_sent(api_client, monkeypatch) -> None:
    def handler(request: Request, body: dict | None) -> Response:
        if request.method == "POST" and request.url.path == "/instance/create":
            return Response(200, json={"instance": {"instanceName": "wa_t1_c1"}, "state": "connecting"})
        if request.method == "POST" and request.url.path == "/webhook/set/wa_t1_c1":
            return Response(200, json={"success": True})
        if request.method == "GET" and request.url.path == "/instance/connectionState/wa_t1_c1":
            return Response(200, json={"state": "open"})
        if request.method == "GET" and request.url.path == "/instance/qrcode/wa_t1_c1":
            return Response(200, json={"base64": "cXItYmFzZTY0"})
        if request.method == "POST" and request.url.path == "/message/sendText/wa_t1_c1":
            return Response(200, json={"key": {"id": "ai-outbound-1"}})
        raise AssertionError(f"Unexpected Evolution request: {request.method} {request.url.path}")

    requests = _install_evolution_service(monkeypatch, handler)
    headers = await _register_and_authenticate(api_client, name="AI Owner", email="ai-owner@example.com")
    await _set_business_profile(
        api_client,
        headers,
        {
            "businessName": "Booking Studio",
            "category": "salon",
            "services": [{"name": "Haircut", "priceFrom": "$40"}],
            "openingHours": "",
            "location": "",
            "bookingLink": "https://booking.example.com",
            "escalationContact": "",
            "faqs": [],
            "forbiddenClaims": [],
        },
    )

    connect = await api_client.post("/api/channels/whatsapp/connect", headers=headers)
    assert connect.status_code == 200, connect.text
    await _update_automation_by_slug(api_client, headers, slug="ai-receptionist", patch={"config": {"autoSend": True}})

    simulated = await api_client.post(
        "/api/dev/simulate-whatsapp-message",
        headers=headers,
        json={"text": "I want to book a haircut", "contactName": "Ava Contact", "phone": "+15551234567"},
    )
    assert simulated.status_code == 200, simulated.text

    detail = await api_client.get(f"/api/conversations/{simulated.json()['conversationId']}", headers=headers)
    assert detail.status_code == 200
    ai_messages = [message for message in detail.json()["messages"] if message["senderType"] == "ai"]
    assert len(ai_messages) == 1
    assert ai_messages[0]["status"] == "sent"
    assert any(method == "POST" and path == "/message/sendText/wa_t1_c1" for method, path, _ in requests)


@pytest.mark.asyncio
async def test_ai_receptionist_disabled_creates_no_draft(api_client, monkeypatch) -> None:
    monkeypatch.setenv("AI_RECEPTIONIST_ENABLED", "false")
    get_settings.cache_clear()
    headers = await _register_and_authenticate(api_client, name="No AI Owner", email="no-ai@example.com")

    connect = await api_client.post("/api/channels/whatsapp/connect", headers=headers)
    assert connect.status_code == 200

    simulated = await api_client.post(
        "/api/dev/simulate-whatsapp-message",
        headers=headers,
        json={"text": "Hello there", "contactName": "Ava Contact", "phone": "+15551234567"},
    )
    assert simulated.status_code == 200

    detail = await api_client.get(f"/api/conversations/{simulated.json()['conversationId']}", headers=headers)
    assert detail.status_code == 200
    assert not any(message["senderType"] == "ai" for message in detail.json()["messages"])


@pytest.mark.asyncio
async def test_can_edit_draft_message(api_client) -> None:
    headers = await _register_and_authenticate(api_client, name="Draft Owner", email="draft-owner@example.com")
    connect = await api_client.post("/api/channels/whatsapp/connect", headers=headers)
    assert connect.status_code == 200

    simulated = await api_client.post(
        "/api/dev/simulate-whatsapp-message",
        headers=headers,
        json={"text": "How much is consultation?", "contactName": "Ava Contact", "phone": "+15551234567"},
    )
    assert simulated.status_code == 200
    detail = await _get_conversation_detail(api_client, headers, simulated.json()["conversationId"])
    draft = next(message for message in detail["messages"] if message["senderType"] == "ai" and message["status"] == "draft")

    updated = await api_client.patch(
        f"/api/messages/{draft['id']}",
        headers=headers,
        json={"text": "Updated operator-reviewed AI draft"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["text"] == "Updated operator-reviewed AI draft"
    assert updated.json()["status"] == "draft"


@pytest.mark.asyncio
async def test_cannot_edit_sent_message(api_client, monkeypatch) -> None:
    def handler(request: Request, body: dict | None) -> Response:
        if request.method == "POST" and request.url.path == "/instance/create":
            return Response(200, json={"instance": {"instanceName": "wa_t1_c1"}, "state": "connecting"})
        if request.method == "POST" and request.url.path == "/webhook/set/wa_t1_c1":
            return Response(200, json={"success": True})
        if request.method == "GET" and request.url.path == "/instance/connectionState/wa_t1_c1":
            return Response(200, json={"state": "open"})
        if request.method == "GET" and request.url.path == "/instance/qrcode/wa_t1_c1":
            return Response(200, json={"base64": "cXItYmFzZTY0"})
        if request.method == "POST" and request.url.path == "/message/sendText/wa_t1_c1":
            return Response(200, json={"key": {"id": "sent-ai-1"}})
        raise AssertionError(f"Unexpected Evolution request: {request.method} {request.url.path}")

    _install_evolution_service(monkeypatch, handler)
    headers = await _register_and_authenticate(api_client, name="Sent Draft Owner", email="sent-draft@example.com")
    connect = await api_client.post("/api/channels/whatsapp/connect", headers=headers)
    assert connect.status_code == 200
    await _update_automation_by_slug(api_client, headers, slug="ai-receptionist", patch={"config": {"autoSend": True}})

    simulated = await api_client.post(
        "/api/dev/simulate-whatsapp-message",
        headers=headers,
        json={"text": "I want to book", "contactName": "Ava Contact", "phone": "+15551234567"},
    )
    assert simulated.status_code == 200
    detail = await _get_conversation_detail(api_client, headers, simulated.json()["conversationId"])
    sent_ai = next(message for message in detail["messages"] if message["senderType"] == "ai")

    updated = await api_client.patch(
        f"/api/messages/{sent_ai['id']}",
        headers=headers,
        json={"text": "Should fail"},
    )
    assert updated.status_code == 400


@pytest.mark.asyncio
async def test_can_send_draft_in_mock_mode(api_client) -> None:
    headers = await _register_and_authenticate(api_client, name="Mock Draft Owner", email="mock-draft@example.com")
    connect = await api_client.post("/api/channels/whatsapp/connect", headers=headers)
    assert connect.status_code == 200

    simulated = await api_client.post(
        "/api/dev/simulate-whatsapp-message",
        headers=headers,
        json={"text": "Tell me about your service", "contactName": "Ava Contact", "phone": "+15551234567"},
    )
    assert simulated.status_code == 200
    detail = await _get_conversation_detail(api_client, headers, simulated.json()["conversationId"])
    draft = next(message for message in detail["messages"] if message["senderType"] == "ai" and message["status"] == "draft")

    sent = await api_client.post(f"/api/messages/{draft['id']}/send-draft", headers=headers)
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "sent"
    assert sent.json()["rawPayload"]["delivery"]["provider"] == "mock"


@pytest.mark.asyncio
async def test_sending_draft_calls_evolution_when_enabled(api_client, monkeypatch) -> None:
    def handler(request: Request, body: dict | None) -> Response:
        if request.method == "POST" and request.url.path == "/instance/create":
            return Response(200, json={"instance": {"instanceName": "wa_t1_c1"}, "state": "connecting"})
        if request.method == "POST" and request.url.path == "/webhook/set/wa_t1_c1":
            return Response(200, json={"success": True})
        if request.method == "GET" and request.url.path == "/instance/connectionState/wa_t1_c1":
            return Response(200, json={"state": "open"})
        if request.method == "GET" and request.url.path == "/instance/qrcode/wa_t1_c1":
            return Response(200, json={"base64": "cXItYmFzZTY0"})
        if request.method == "POST" and request.url.path == "/message/sendText/wa_t1_c1":
            return Response(200, json={"key": {"id": "draft-send-1"}})
        raise AssertionError(f"Unexpected Evolution request: {request.method} {request.url.path}")

    requests = _install_evolution_service(monkeypatch, handler)
    headers = await _register_and_authenticate(api_client, name="Draft Send Owner", email="draft-send@example.com")
    connect = await api_client.post("/api/channels/whatsapp/connect", headers=headers)
    assert connect.status_code == 200

    simulated = await api_client.post(
        "/api/dev/simulate-whatsapp-message",
        headers=headers,
        json={"text": "Hello there", "contactName": "Ava Contact", "phone": "+15551234567"},
    )
    assert simulated.status_code == 200
    detail = await _get_conversation_detail(api_client, headers, simulated.json()["conversationId"])
    draft = next(message for message in detail["messages"] if message["senderType"] == "ai" and message["status"] == "draft")

    sent = await api_client.post(f"/api/messages/{draft['id']}/send-draft", headers=headers)
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "sent"
    assert any(method == "POST" and path == "/message/sendText/wa_t1_c1" for method, path, _ in requests)


@pytest.mark.asyncio
async def test_cannot_send_another_tenants_draft(api_client) -> None:
    owner_headers = await _register_and_authenticate(api_client, name="Tenant One", email="tenant-one@example.com")
    other_headers = await _register_and_authenticate(api_client, name="Tenant Two", email="tenant-two@example.com")
    connect = await api_client.post("/api/channels/whatsapp/connect", headers=owner_headers)
    assert connect.status_code == 200

    simulated = await api_client.post(
        "/api/dev/simulate-whatsapp-message",
        headers=owner_headers,
        json={"text": "Hello there", "contactName": "Ava Contact", "phone": "+15551234567"},
    )
    assert simulated.status_code == 200
    detail = await _get_conversation_detail(api_client, owner_headers, simulated.json()["conversationId"])
    draft = next(message for message in detail["messages"] if message["senderType"] == "ai" and message["status"] == "draft")

    sent = await api_client.post(f"/api/messages/{draft['id']}/send-draft", headers=other_headers)
    assert sent.status_code == 404


@pytest.mark.asyncio
async def test_can_discard_draft(api_client) -> None:
    headers = await _register_and_authenticate(api_client, name="Discard Owner", email="discard@example.com")
    connect = await api_client.post("/api/channels/whatsapp/connect", headers=headers)
    assert connect.status_code == 200

    simulated = await api_client.post(
        "/api/dev/simulate-whatsapp-message",
        headers=headers,
        json={"text": "Hello there", "contactName": "Ava Contact", "phone": "+15551234567"},
    )
    assert simulated.status_code == 200
    detail = await _get_conversation_detail(api_client, headers, simulated.json()["conversationId"])
    draft = next(message for message in detail["messages"] if message["senderType"] == "ai" and message["status"] == "draft")

    discarded = await api_client.delete(f"/api/messages/{draft['id']}", headers=headers)
    assert discarded.status_code == 200, discarded.text
    assert discarded.json() == {"ok": True}

    detail_after = await _get_conversation_detail(api_client, headers, simulated.json()["conversationId"])
    discarded_message = next(message for message in detail_after["messages"] if message["id"] == draft["id"])
    assert discarded_message["status"] == "discarded"


@pytest.mark.asyncio
async def test_cannot_discard_sent_message(api_client) -> None:
    headers = await _register_and_authenticate(api_client, name="Discard Sent Owner", email="discard-sent@example.com")
    connect = await api_client.post("/api/channels/whatsapp/connect", headers=headers)
    assert connect.status_code == 200

    simulated = await api_client.post(
        "/api/dev/simulate-whatsapp-message",
        headers=headers,
        json={"text": "Hello there", "contactName": "Ava Contact", "phone": "+15551234567"},
    )
    assert simulated.status_code == 200
    detail = await _get_conversation_detail(api_client, headers, simulated.json()["conversationId"])
    draft = next(message for message in detail["messages"] if message["senderType"] == "ai" and message["status"] == "draft")
    sent = await api_client.post(f"/api/messages/{draft['id']}/send-draft", headers=headers)
    assert sent.status_code == 200

    discarded = await api_client.delete(f"/api/messages/{draft['id']}", headers=headers)
    assert discarded.status_code == 400


@pytest.mark.asyncio
async def test_manual_human_send_still_works(api_client) -> None:
    headers = await _register_and_authenticate(api_client, name="Manual Owner", email="manual-owner@example.com")
    connect = await api_client.post("/api/channels/whatsapp/connect", headers=headers)
    assert connect.status_code == 200

    simulated = await api_client.post(
        "/api/dev/simulate-whatsapp-message",
        headers=headers,
        json={"text": "Hello there", "contactName": "Ava Contact", "phone": "+15551234567"},
    )
    assert simulated.status_code == 200

    sent = await api_client.post(
        f"/api/conversations/{simulated.json()['conversationId']}/send-message",
        headers=headers,
        json={"text": "Manual follow-up"},
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["senderType"] == "human"
    assert sent.json()["status"] == "sent"


@pytest.mark.asyncio
async def test_handoff_still_marks_conversation_needs_human(api_client) -> None:
    headers = await _register_and_authenticate(api_client, name="Handoff Owner", email="handoff-owner@example.com")
    connect = await api_client.post("/api/channels/whatsapp/connect", headers=headers)
    assert connect.status_code == 200

    simulated = await api_client.post(
        "/api/dev/simulate-whatsapp-message",
        headers=headers,
        json={"text": "Hello there", "contactName": "Ava Contact", "phone": "+15551234567"},
    )
    assert simulated.status_code == 200

    handoff = await api_client.post(f"/api/conversations/{simulated.json()['conversationId']}/handoff", headers=headers)
    assert handoff.status_code == 200, handoff.text
    assert handoff.json()["status"] == "needs_human"


@pytest.mark.asyncio
async def test_handoff_is_sticky_after_followup_inbound_message(api_client) -> None:
    headers = await _register_and_authenticate(api_client, name="Sticky Handoff", email="sticky-handoff@example.com")
    connect = await api_client.post("/api/channels/whatsapp/connect", headers=headers)
    assert connect.status_code == 200

    first = await api_client.post(
        "/api/dev/simulate-whatsapp-message",
        headers=headers,
        json={"text": "I need a human agent", "contactName": "Mia", "phone": "+15551234567"},
    )
    assert first.status_code == 200
    conversation_id = first.json()["conversationId"]

    second = await api_client.post(
        "/api/dev/simulate-whatsapp-message",
        headers=headers,
        json={"text": "Also, what are your opening hours?", "contactName": "Mia", "phone": "+15551234567"},
    )
    assert second.status_code == 200
    assert second.json().get("ignored") is not True

    conversations = await api_client.get("/api/conversations", headers=headers)
    assert conversations.status_code == 200
    conversation = conversations.json()["conversations"][0]
    assert conversation["id"] == conversation_id
    assert conversation["status"] == "needs_human"
    assert conversation["latestMessage"] == "Also, what are your opening hours?"
    assert conversation["unreadCount"] == 2

    detail = await _get_conversation_detail(api_client, headers, conversation_id)
    assert not any(message["senderType"] == "ai" for message in detail["messages"])

    notifications = await api_client.get("/api/notifications", headers=headers)
    assert notifications.status_code == 200
    handoff_events = [event for event in notifications.json()["notifications"] if event["type"] == "needs_human"]
    assert len(handoff_events) == 1


@pytest.mark.asyncio
async def test_existing_lead_update_does_not_duplicate_new_lead_notification(api_client) -> None:
    headers = await _register_and_authenticate(api_client, name="Lead Notify", email="lead-notify@example.com")
    connect = await api_client.post("/api/channels/whatsapp/connect", headers=headers)
    assert connect.status_code == 200

    first = await api_client.post(
        "/api/dev/simulate-whatsapp-message",
        headers=headers,
        json={"text": "I want to book teeth whitening and know the price", "contactName": "Mia", "phone": "+15551234567"},
    )
    assert first.status_code == 200
    second = await api_client.post(
        "/api/dev/simulate-whatsapp-message",
        headers=headers,
        json={"text": "I still want the price for teeth whitening", "contactName": "Mia", "phone": "+15551234567"},
    )
    assert second.status_code == 200

    notifications = await api_client.get("/api/notifications", headers=headers)
    assert notifications.status_code == 200
    new_lead_events = [event for event in notifications.json()["notifications"] if event["type"] == "new_lead"]
    assert len(new_lead_events) == 1


@pytest.mark.asyncio
async def test_already_needs_human_does_not_duplicate_notification(api_client) -> None:
    headers = await _register_and_authenticate(api_client, name="Human Notify", email="human-notify@example.com")
    connect = await api_client.post("/api/channels/whatsapp/connect", headers=headers)
    assert connect.status_code == 200

    first = await api_client.post(
        "/api/dev/simulate-whatsapp-message",
        headers=headers,
        json={"text": "I need a human agent", "contactName": "Mia", "phone": "+15551234567"},
    )
    assert first.status_code == 200
    second = await api_client.post(
        "/api/dev/simulate-whatsapp-message",
        headers=headers,
        json={"text": "human please call me", "contactName": "Mia", "phone": "+15551234567"},
    )
    assert second.status_code == 200

    notifications = await api_client.get("/api/notifications", headers=headers)
    assert notifications.status_code == 200
    handoff_events = [event for event in notifications.json()["notifications"] if event["type"] == "needs_human"]
    assert len(handoff_events) == 1


@pytest.mark.asyncio
async def test_test_notification_endpoint_creates_event(api_client) -> None:
    headers = await _register_and_authenticate(api_client, name="Test Notify", email="test-notify-api@example.com")
    response = await api_client.post("/api/notifications/test", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["notification"]["type"] == "test"


@pytest.mark.asyncio
async def test_webhook_notification_delivery_posts_expected_payload(api_client, monkeypatch) -> None:
    requests: list[tuple[str, str, dict | None]] = []

    def handler(request: Request) -> Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else None
        requests.append((request.method, str(request.url), body))
        return Response(200, json={"ok": True})

    original_init = __import__("bot.services.notification_service", fromlist=["NotificationService"]).NotificationService.__init__

    def patched_init(self, session, *, transport=None, timeout_seconds=5.0):
        return original_init(self, session, transport=MockTransport(handler), timeout_seconds=timeout_seconds)

    monkeypatch.setattr("bot.services.notification_service.NotificationService.__init__", patched_init)

    headers = await _register_and_authenticate(api_client, name="Webhook Notify", email="webhook-notify@example.com")
    update = await api_client.patch(
        "/api/notification-settings",
        headers=headers,
        json={"notificationChannel": "webhook", "notificationTarget": "https://hooks.example.com/operator"},
    )
    assert update.status_code == 200

    connect = await api_client.post("/api/channels/whatsapp/connect", headers=headers)
    assert connect.status_code == 200
    simulated = await api_client.post(
        "/api/dev/simulate-whatsapp-message",
        headers=headers,
        json={"text": "I want to book teeth whitening and know the price", "contactName": "Mia", "phone": "+15551234567"},
    )
    assert simulated.status_code == 200

    assert any(body and body["type"] == "new_lead" for _, _, body in requests)


@pytest.mark.asyncio
async def test_evolution_webhook_normalizes_extended_text_and_ignores_non_text_and_from_me(api_client, monkeypatch) -> None:
    _install_evolution_service(monkeypatch, lambda _request, _body: Response(200, json={"ok": True}), webhook_secret="whsec-test")
    headers = await _register_and_authenticate(api_client, name="Webhook Owner", email="webhook@example.com")

    connect = await api_client.post("/api/channels/whatsapp/connect", headers=headers)
    channel_id = connect.json()["channel"]["id"]

    unauthorized = await api_client.post(
        f"/api/webhooks/evolution/{channel_id}",
        json={"data": {"message": {"conversation": "hello"}}},
    )
    assert unauthorized.status_code == 401

    extended_text = await api_client.post(
        f"/api/webhooks/evolution/{channel_id}?secret=whsec-test",
        json={
            "data": {
                "pushName": "Jamie Buyer",
                "message": {
                    "key": {"remoteJid": "15557778888@s.whatsapp.net", "id": "msg-ext-1"},
                    "message": {"extendedTextMessage": {"text": "I am interested in the price and want to schedule"}},
                },
            }
        },
    )
    assert extended_text.status_code == 200, extended_text.text
    assert extended_text.json()["leadId"] is not None

    ignored_non_text = await api_client.post(
        f"/api/webhooks/evolution/{channel_id}?secret=whsec-test",
        json={
            "event": "messages.upsert",
            "data": {
                "message": {
                    "key": {"remoteJid": "15557778888@s.whatsapp.net", "id": "msg-reaction-1"},
                    "message": {"reactionMessage": {"text": "thumbs-up"}},
                }
            },
        },
    )
    assert ignored_non_text.status_code == 200
    assert ignored_non_text.json()["ignored"] is True

    ignored_from_me = await api_client.post(
        f"/api/webhooks/evolution/{channel_id}",
        headers={"X-Evolution-Webhook-Secret": "whsec-test"},
        json={
            "data": {
                "message": {
                    "key": {
                        "remoteJid": "15557778888@s.whatsapp.net",
                        "id": "msg-out-1",
                        "fromMe": True,
                    },
                    "conversation": "This should be ignored",
                }
            }
        },
    )
    assert ignored_from_me.status_code == 200
    assert ignored_from_me.json()["ignored"] is True

    conversations = await api_client.get("/api/conversations", headers=headers)
    assert conversations.status_code == 200
    payload = conversations.json()["conversations"]
    assert len(payload) == 1
    assert payload[0]["latestMessage"] == "I am interested in the price and want to schedule"

    leads = await api_client.get("/api/leads", headers=headers)
    assert leads.status_code == 200
    assert len(leads.json()["leads"]) == 1
