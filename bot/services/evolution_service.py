from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

import httpx

if TYPE_CHECKING:
    from bot.db.models import ChannelAccount


class EvolutionApiError(RuntimeError):
    pass


class EvolutionWebhookAuthError(ValueError):
    pass


@dataclass(frozen=True)
class EvolutionSettings:
    enabled: bool
    api_base_url: str | None
    api_key: str | None
    webhook_base_url: str | None
    webhook_secret: str | None
    timeout_seconds: float = 10.0
    send_ai_replies: bool = False

    @classmethod
    def from_env(cls) -> EvolutionSettings:
        return cls(
            enabled=os.getenv("EVOLUTION_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"},
            api_base_url=(os.getenv("EVOLUTION_API_BASE_URL") or "").strip() or None,
            api_key=(os.getenv("EVOLUTION_API_KEY") or "").strip() or None,
            webhook_base_url=(os.getenv("EVOLUTION_WEBHOOK_BASE_URL") or "").strip() or None,
            webhook_secret=(os.getenv("EVOLUTION_WEBHOOK_SECRET") or "").strip() or None,
            timeout_seconds=float(os.getenv("EVOLUTION_TIMEOUT_SECONDS", "10")),
            send_ai_replies=os.getenv("SEND_AI_REPLIES", "false").strip().lower() in {"1", "true", "yes", "on"},
        )

    @property
    def configured(self) -> bool:
        return self.enabled and bool(self.api_base_url and self.api_key)


@dataclass(frozen=True)
class EvolutionChannelState:
    external_account_id: str
    status: str
    qr_code: str | None
    metadata: dict[str, Any]


class EvolutionWhatsAppService:
    def __init__(
        self,
        settings: EvolutionSettings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings or EvolutionSettings.from_env()
        self._transport = transport

    @classmethod
    def from_env(cls) -> EvolutionWhatsAppService:
        return cls()

    @property
    def enabled(self) -> bool:
        return self.settings.configured

    def build_instance_name(self, tenant_id: int, channel_account_id: int) -> str:
        return f"wa_t{tenant_id}_c{channel_account_id}"

    def validate_webhook_secret(self, provided_secret: str | None) -> None:
        expected = self.settings.webhook_secret
        if expected and provided_secret != expected:
            raise EvolutionWebhookAuthError("Invalid Evolution webhook secret")

    async def create_instance(self, *, tenant_id: int, channel_account_id: int, display_name: str) -> EvolutionChannelState:
        instance_name = self.build_instance_name(tenant_id, channel_account_id)
        payload = {
            "instanceName": instance_name,
            "integration": "WHATSAPP-BAILEYS",
            "qrcode": True,
            "number": "",
            "displayName": display_name,
        }
        create_response = await self._request("POST", "/instance/create", json=payload)
        await self.configure_webhook(channel_account_id=channel_account_id, instance_name=instance_name)
        status_payload = await self._safe_request("GET", f"/instance/connectionState/{instance_name}") or {}
        qr_payload = await self._safe_request("GET", f"/instance/qrcode/{instance_name}") or {}
        return EvolutionChannelState(
            external_account_id=instance_name,
            status=self._map_status(self._extract_status(status_payload or create_response)),
            qr_code=self._extract_qr_code(qr_payload or create_response),
            metadata={"provider": "evolution", "instance": instance_name},
        )

    async def get_instance_status(self, channel_account: ChannelAccount) -> EvolutionChannelState:
        instance_name = self._require_instance_name(channel_account)
        payload = await self._request("GET", f"/instance/connectionState/{instance_name}")
        qr_payload = await self._safe_request("GET", f"/instance/qrcode/{instance_name}") or {}
        return EvolutionChannelState(
            external_account_id=instance_name,
            status=self._map_status(self._extract_status(payload)),
            qr_code=self._extract_qr_code(qr_payload),
            metadata={"provider": "evolution", "instance": instance_name, "rawStatus": payload},
        )

    async def get_qr_code(self, channel_account: ChannelAccount) -> EvolutionChannelState:
        instance_name = self._require_instance_name(channel_account)
        payload = await self._request("GET", f"/instance/qrcode/{instance_name}")
        status_payload = await self._safe_request("GET", f"/instance/connectionState/{instance_name}") or {}
        return EvolutionChannelState(
            external_account_id=instance_name,
            status=self._map_status(self._extract_status(status_payload)),
            qr_code=self._extract_qr_code(payload),
            metadata={"provider": "evolution", "instance": instance_name},
        )

    async def refresh_qr_code(self, channel_account: ChannelAccount) -> EvolutionChannelState:
        instance_name = self._require_instance_name(channel_account)
        await self._safe_request("GET", f"/instance/connect/{instance_name}")
        return await self.get_qr_code(channel_account)

    async def disconnect_instance(self, channel_account: ChannelAccount) -> EvolutionChannelState:
        instance_name = self._require_instance_name(channel_account)
        await self._safe_request("DELETE", f"/instance/logout/{instance_name}")
        await self._safe_request("DELETE", f"/instance/delete/{instance_name}")
        return EvolutionChannelState(
            external_account_id=instance_name,
            status="disconnected",
            qr_code=None,
            metadata={"provider": "evolution", "instance": instance_name},
        )

    async def send_message(self, channel_account: ChannelAccount, *, to: str, text: str) -> dict[str, Any]:
        instance_name = self._require_instance_name(channel_account)
        payload = await self._request(
            "POST",
            f"/message/sendText/{instance_name}",
            json={"number": self._normalize_phone_number(to), "text": text},
        )
        return {
            "provider": "evolution",
            "instance": instance_name,
            "messageId": self._extract_message_id(payload),
            "raw": payload,
        }

    async def configure_webhook(self, *, channel_account_id: int, instance_name: str) -> dict[str, Any]:
        url = self._build_webhook_url(channel_account_id)
        if url is None:
            return {"ok": False, "reason": "missing-webhook-base-url"}
        payload = {
            "url": url,
            "enabled": True,
            "webhookByEvents": False,
            "events": ["MESSAGES_UPSERT", "MESSAGES_UPDATE", "CONNECTION_UPDATE"],
        }
        # TODO: confirm the exact Evolution webhook endpoint and payload contract in production.
        return await self._request("POST", f"/webhook/set/{instance_name}", json=payload)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            raise EvolutionApiError("Evolution API is not enabled")
        async with self._build_client() as client:
            try:
                response = await client.request(method, path, json=json, params=params)
                response.raise_for_status()
                if not response.content:
                    return {}
                data = response.json()
            except httpx.HTTPError as exc:
                raise EvolutionApiError(f"Evolution API request failed: {exc}") from exc
            except ValueError as exc:
                raise EvolutionApiError("Evolution API returned non-JSON response") from exc
        return data if isinstance(data, dict) else {"data": data}

    async def _safe_request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        try:
            return await self._request(method, path, json=json)
        except EvolutionApiError:
            return None

    def _build_client(self) -> httpx.AsyncClient:
        assert self.settings.api_base_url is not None
        assert self.settings.api_key is not None
        return httpx.AsyncClient(
            base_url=self.settings.api_base_url.rstrip("/"),
            headers={"apikey": self.settings.api_key},
            timeout=httpx.Timeout(self.settings.timeout_seconds, connect=min(self.settings.timeout_seconds, 5.0)),
            transport=self._transport,
        )

    def _build_webhook_url(self, channel_account_id: int) -> str | None:
        if not self.settings.webhook_base_url:
            return None
        base = self.settings.webhook_base_url.rstrip("/")
        query = ""
        if self.settings.webhook_secret:
            query = "?" + urlencode({"secret": self.settings.webhook_secret})
        return f"{base}/api/webhooks/evolution/{channel_account_id}{query}"

    def _require_instance_name(self, channel_account: ChannelAccount) -> str:
        instance_name = (channel_account.external_account_id or "").strip()
        if not instance_name:
            raise EvolutionApiError("Channel is missing Evolution instance metadata")
        return instance_name

    def _map_status(self, raw_status: str | None) -> str:
        normalized = (raw_status or "").strip().lower()
        if normalized in {"open", "connected", "online"}:
            return "connected"
        if normalized in {"close", "closed", "disconnected", "logout", "offline"}:
            return "disconnected"
        if normalized in {"error", "failed", "conflict"}:
            return "error"
        if normalized in {"qrcode", "qr", "pending", "connecting", "pairing", "startup"}:
            return "pending"
        return "pending"

    def _extract_status(self, payload: dict[str, Any]) -> str | None:
        candidates = [
            payload.get("state"),
            payload.get("status"),
            payload.get("instance", {}).get("state") if isinstance(payload.get("instance"), dict) else None,
            payload.get("instance", {}).get("status") if isinstance(payload.get("instance"), dict) else None,
            payload.get("data", {}).get("state") if isinstance(payload.get("data"), dict) else None,
            payload.get("data", {}).get("status") if isinstance(payload.get("data"), dict) else None,
        ]
        for candidate in candidates:
            if candidate:
                return str(candidate)
        return None

    def _extract_qr_code(self, payload: dict[str, Any]) -> str | None:
        candidates = [
            payload.get("base64"),
            payload.get("qrcode"),
            payload.get("qrCode"),
            payload.get("data", {}).get("base64") if isinstance(payload.get("data"), dict) else None,
            payload.get("data", {}).get("qrcode") if isinstance(payload.get("data"), dict) else None,
            payload.get("data", {}).get("qrCode") if isinstance(payload.get("data"), dict) else None,
        ]
        for candidate in candidates:
            if not candidate:
                continue
            value = str(candidate)
            if value.startswith("data:image"):
                return value
            if value.startswith("http://") or value.startswith("https://"):
                return value
            return f"data:image/png;base64,{value}"
        return None

    def _extract_message_id(self, payload: dict[str, Any]) -> str | None:
        candidates = [
            payload.get("key", {}).get("id") if isinstance(payload.get("key"), dict) else None,
            payload.get("id"),
            payload.get("messageId"),
            payload.get("data", {}).get("key", {}).get("id")
            if isinstance(payload.get("data"), dict) and isinstance(payload["data"].get("key"), dict)
            else None,
        ]
        for candidate in candidates:
            if candidate:
                return str(candidate)
        return None

    def _normalize_phone_number(self, value: str) -> str:
        number = value.split("@", 1)[0]
        return "".join(character for character in number if character.isdigit())
