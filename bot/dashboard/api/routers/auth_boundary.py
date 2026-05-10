from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import AppKind, get_settings
from bot.db.session import get_session
from bot.services.telegram_webapp_auth import TelegramWebAppIdentity

from ..dependencies import get_identity
from ._shared import EmailPasswordLoginRequest, LanguageUpdateRequest
from .auth import (
    identity_profile_payload,
    miniapp_token_payload,
    providers_payload,
    set_identity_language_payload,
    telegram_login_payload,
    telegram_widget_config_payload,
    email_login_payload,
)


router = APIRouter(prefix="/api", tags=["auth"])


def _normalize_app_boundary(value: str | None) -> AppKind | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    if normalized in {"admin", "agents"}:
        return normalized
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid X-App-Boundary header")


async def get_app_boundary(
    x_app_boundary: str | None = Header(default=None, alias="X-App-Boundary"),
) -> AppKind | None:
    return _normalize_app_boundary(x_app_boundary)


def require_app_boundary(expected: AppKind):
    async def _require_app_boundary(
        app_boundary: AppKind | None = Depends(get_app_boundary),
        identity: TelegramWebAppIdentity = Depends(get_identity),
    ) -> AppKind:
        if identity.user_id in get_settings().bot_owner_ids:
            return app_boundary or expected

        if app_boundary != expected:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This route requires the '{expected}' app boundary",
            )
        return app_boundary

    return _require_app_boundary


require_admin_boundary = require_app_boundary("admin")
require_agents_boundary = require_app_boundary("agents")


def require_any_boundary(allowed: list[AppKind]):
    async def _require_any_boundary(
        app_boundary: AppKind | None = Depends(get_app_boundary),
        identity: TelegramWebAppIdentity = Depends(get_identity),
    ) -> AppKind:
        if identity.user_id in get_settings().bot_owner_ids:
            return app_boundary or allowed[0]

        if app_boundary not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This route requires one of the following app boundaries: {', '.join(allowed)}",
            )
        return app_boundary

    return _require_any_boundary


@router.get("/auth/providers")
async def auth_providers() -> dict[str, Any]:
    return await providers_payload()


@router.get("/auth/telegram/widget-config")
async def telegram_login_widget_config() -> dict[str, Any]:
    return await telegram_widget_config_payload()


@router.post("/auth/telegram/login")
async def telegram_login(
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await telegram_login_payload(payload=payload, session=session)


@router.post("/auth/email/login")
async def email_password_login(
    payload: EmailPasswordLoginRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await email_login_payload(email=payload.email, password=payload.password, session=session)


@router.post("/auth/miniapp/token")
async def miniapp_token(
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
    app_boundary: AppKind | None = Depends(get_app_boundary),
) -> dict[str, Any]:
    init_data = str(payload.get("init_data") or "")
    return await miniapp_token_payload(session=session, init_data=init_data, app_boundary=app_boundary)


@router.post("/auth/miniapp-login")
async def miniapp_login_compat(
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
    app_boundary: AppKind | None = Depends(get_app_boundary),
) -> dict[str, Any]:
    init_data = str(payload.get("init_data") or "")
    return await miniapp_token_payload(session=session, init_data=init_data, app_boundary=app_boundary)


@router.get("/auth/me")
async def auth_me(
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await identity_profile_payload(identity=identity, session=session)


@router.patch("/auth/language")
async def auth_set_language(
    payload: LanguageUpdateRequest,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await set_identity_language_payload(
        language_code=payload.language_code,
        identity=identity,
        session=session,
    )


__all__ = ["router"]
