from __future__ import annotations

import json

import pytest
from httpx import MockTransport, Request, Response

from bot.services.evolution_service import (
    EvolutionSettings,
    EvolutionWebhookAuthError,
    EvolutionWhatsAppService,
)


@pytest.mark.asyncio
async def test_evolution_service_create_instance_configures_webhook_and_maps_status() -> None:
    requests: list[tuple[str, str, dict | None]] = []

    def handler(request: Request) -> Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else None
        requests.append((request.method, request.url.path, body))
        if request.method == "POST" and request.url.path == "/instance/create":
            return Response(200, json={"state": "connecting"})
        if request.method == "POST" and request.url.path == "/webhook/set/wa_t7_c12":
            return Response(200, json={"ok": True})
        if request.method == "GET" and request.url.path == "/instance/connectionState/wa_t7_c12":
            return Response(200, json={"state": "open"})
        if request.method == "GET" and request.url.path == "/instance/qrcode/wa_t7_c12":
            return Response(200, json={"base64": "cXItY29kZQ=="})
        raise AssertionError(f"Unexpected request: {request.method} {request.url.path}")

    service = EvolutionWhatsAppService(
        EvolutionSettings(
            enabled=True,
            api_base_url="https://evolution.test",
            api_key="top-secret",
            webhook_base_url="https://preview.example.com",
            webhook_secret="whsec",
        ),
        transport=MockTransport(handler),
    )

    state = await service.create_instance(tenant_id=7, channel_account_id=12, display_name="Clinic Line")
    assert state.external_account_id == "wa_t7_c12"
    assert state.status == "connected"
    assert state.qr_code == "data:image/png;base64,cXItY29kZQ=="

    assert requests[0] == (
        "POST",
        "/instance/create",
        {
            "instanceName": "wa_t7_c12",
            "integration": "WHATSAPP-BAILEYS",
            "qrcode": True,
            "number": "",
            "displayName": "Clinic Line",
        },
    )
    assert requests[1] == (
        "POST",
        "/webhook/set/wa_t7_c12",
        {
            "url": "https://preview.example.com/api/webhooks/evolution/12?secret=whsec",
            "enabled": True,
            "webhookByEvents": False,
            "events": ["MESSAGES_UPSERT", "MESSAGES_UPDATE", "CONNECTION_UPDATE"],
        },
    )


def test_evolution_service_validates_webhook_secret() -> None:
    service = EvolutionWhatsAppService(
        EvolutionSettings(
            enabled=False,
            api_base_url=None,
            api_key=None,
            webhook_base_url=None,
            webhook_secret="whsec",
        )
    )

    service.validate_webhook_secret("whsec")
    with pytest.raises(EvolutionWebhookAuthError):
        service.validate_webhook_secret("wrong")
