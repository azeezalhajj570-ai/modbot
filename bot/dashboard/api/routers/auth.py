from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import AppKind, get_settings
from bot.dashboard.api.auth import (
    DashboardJWTError,
    TelegramWebAppAuthError,
    issue_dashboard_token_for_init_data,
    issue_dashboard_token_for_browser_credentials,
    issue_dashboard_token_for_telegram_login,
)
from bot.db.models import Group, GroupAdminRole
from bot.db.session import get_session
from bot.services.telegram_webapp_auth import TelegramWebAppIdentity
from bot.services.user_service import UserService
from bot.services.messaging_service import MessagingService, MessagingAuthError

from ..dependencies import (
    _bot_install_username,
    build_bot_install_link,
    build_identity_profile,
    get_identity,
    list_identity_bot_install_groups,
)
from ._shared import (
    BOT_INSTALL_PERMISSION_KEYS,
    BotInstallLinkRequest,
    EmailPasswordLoginRequest,
    LanguageUpdateRequest,
)


router = APIRouter(tags=["auth"])


async def providers_payload() -> dict[str, Any]:
    settings = get_settings()
    return {
        "telegram": {"enabled": True, "bot_username": await _bot_install_username()},
        "password": {"enabled": bool(settings.dashboard_browser_users)},
    }


async def telegram_widget_config_payload() -> dict[str, str]:
    return {"bot_username": await _bot_install_username()}


async def telegram_login_payload(
    *,
    payload: dict[str, Any],
    session: AsyncSession,
) -> dict[str, Any]:
    init_data = str(payload.get("initData") or payload.get("init_data") or "")
    if init_data:
        try:
            context = await MessagingService(session).authenticate_telegram(init_data)
            return {
                "token": context.access_token,
                "access_token": context.access_token,
                "user": {
                    "id": context.user.id,
                    "telegramId": context.user.tg_user_id,
                    "username": context.user.username,
                    "fullName": context.user.full_name,
                },
                "tenant": {
                    "id": context.tenant.id,
                    "name": context.tenant.name,
                },
            }
        except (TelegramWebAppAuthError, MessagingAuthError) as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    try:
        token, identity = await issue_dashboard_token_for_telegram_login(session=session, payload=payload)
        return {
            "token": token,
            "access_token": token,
            "user": {
                "id": identity.user_id,
                "telegramId": identity.user_id,
                "username": identity.username,
            },
        }
    except TelegramWebAppAuthError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


async def email_login_payload(
    *,
    email: str,
    password: str,
    session: AsyncSession,
) -> dict[str, Any]:
    try:
        token, matched_user, identity = await issue_dashboard_token_for_browser_credentials(
            session=session,
            identifier=email,
            password=password,
        )
        return {
            "token": token,
            "access_token": token,
            "user": {
                "id": identity.user_id,
                "email": matched_user.email,
                "username": identity.username,
            },
        }
    except DashboardJWTError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid email or password") from exc


async def miniapp_token_payload(
    *,
    session: AsyncSession,
    init_data: str,
    app_boundary: AppKind | None = None,
) -> dict[str, Any]:
    if app_boundary in {"admin", "agents"}:
        try:
            token, identity = issue_dashboard_token_for_init_data(init_data)
        except TelegramWebAppAuthError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        return {
            "token": token,
            "access_token": token,
            "user": {
                "id": identity.user_id,
                "telegramId": identity.user_id,
                "username": identity.username,
            },
        }

    try:
        context = await MessagingService(session).authenticate_telegram(init_data, app_boundary=app_boundary)
        return {
            "token": context.access_token,
            "access_token": context.access_token,
            "user": {
                "id": context.user.id,
                "telegramId": context.user.tg_user_id,
                "username": context.user.username,
                "fullName": context.user.full_name,
            },
            "tenant": {
                "id": context.tenant.id,
                "name": context.tenant.name,
            },
        }
    except (TelegramWebAppAuthError, MessagingAuthError) as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


async def identity_profile_payload(
    *,
    identity: TelegramWebAppIdentity,
    session: AsyncSession,
) -> dict[str, Any]:
    return await build_identity_profile(session, identity=identity)


async def set_identity_language_payload(
    *,
    language_code: str,
    identity: TelegramWebAppIdentity,
    session: AsyncSession,
) -> dict[str, str]:
    full_name = " ".join(part for part in [identity.first_name, identity.last_name] if part).strip() or None
    await UserService(session).set_language(
        tg_user_id=identity.user_id,
        language_code=language_code,
        username=identity.username,
        full_name=full_name,
    )
    return {"status": "ok", "language_code": language_code}


async def bot_install_groups_payload(
    *,
    identity: TelegramWebAppIdentity,
    session: AsyncSession,
) -> list[dict[str, Any]]:
    return await list_identity_bot_install_groups(session, identity=identity)


async def bot_install_links_payload(
    *,
    payload: BotInstallLinkRequest,
    identity: TelegramWebAppIdentity,
    session: AsyncSession,
) -> dict[str, Any]:
    invalid_permissions = [item for item in payload.permissions if item not in BOT_INSTALL_PERMISSION_KEYS]
    if invalid_permissions:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported bot install permissions: {', '.join(sorted(set(invalid_permissions)))}",
        )

    selected_groups: list[dict[str, Any]] = []
    if payload.groups:
        seen_tg_group_ids: set[int] = set()
        eligible_by_tg_id = {
            int(item["tg_group_id"]): item
            for item in await list_identity_bot_install_groups(session, identity=identity)
        }
        for item in payload.groups:
            tg_group_id = int(item.tg_group_id)
            if tg_group_id in seen_tg_group_ids:
                continue
            seen_tg_group_ids.add(tg_group_id)
            eligible = eligible_by_tg_id.get(tg_group_id)
            if eligible is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="One or more selected groups are not eligible for this Telegram account",
                )
            selected_groups.append(
                {
                    "group_id": eligible.get("managed_group_id"),
                    "tg_group_id": tg_group_id,
                    "title": eligible.get("title") or item.title,
                }
            )
    else:
        requested_group_ids = [int(group_id) for group_id in payload.group_ids]
        unique_group_ids = list(dict.fromkeys(requested_group_ids))
        rows = (
            await session.execute(
                select(Group.id, Group.title, Group.tg_group_id)
                .join(GroupAdminRole, GroupAdminRole.group_id == Group.id)
                .where(
                    GroupAdminRole.user_id == identity.user_id,
                    Group.is_active.is_(True),
                    Group.id.in_(unique_group_ids),
                )
                .order_by(Group.title.asc())
            )
        ).all()
        groups_by_id = {
            int(row.id): {"group_id": int(row.id), "tg_group_id": int(row.tg_group_id), "title": row.title}
            for row in rows
        }
        missing_group_ids = [group_id for group_id in unique_group_ids if group_id not in groups_by_id]
        if missing_group_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="One or more selected groups are not managed by this admin",
            )
        selected_groups = [groups_by_id[group_id] for group_id in unique_group_ids]

    username = await _bot_install_username()
    link = build_bot_install_link(bot_username=username, permissions=payload.permissions)
    return {
        "bot_username": username,
        "permissions": payload.permissions,
        "manual_confirmation_required": True,
        "links": [{**group, "url": link} for group in selected_groups],
    }


@router.get("/auth/providers")
async def auth_providers() -> dict[str, Any]:
    return await providers_payload()


@router.get("/auth/telegram/widget-config")
async def telegram_login_widget_config() -> dict[str, str]:
    return await telegram_widget_config_payload()


@router.post("/auth/telegram/login")
@router.post("/api/auth/telegram")
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
) -> dict[str, Any]:
    init_data = str(payload.get("init_data") or "")
    return await miniapp_token_payload(session=session, init_data=init_data)


@router.get("/webapp/auth/me")
async def webapp_me(
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await identity_profile_payload(identity=identity, session=session)


@router.patch("/webapp/auth/language")
async def webapp_set_language(
    payload: LanguageUpdateRequest,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    return await set_identity_language_payload(
        language_code=payload.language_code,
        identity=identity,
        session=session,
    )


@router.get("/webapp/bot/install-groups")
async def webapp_bot_install_groups(
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    return await bot_install_groups_payload(identity=identity, session=session)


@router.post("/webapp/bot/install-links")
async def webapp_bot_install_links(
    payload: BotInstallLinkRequest,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await bot_install_links_payload(payload=payload, identity=identity, session=session)


__all__ = [
    "auth_providers",
    "bot_install_groups_payload",
    "bot_install_links_payload",
    "email_login_payload",
    "identity_profile_payload",
    "miniapp_token_payload",
    "providers_payload",
    "router",
    "set_identity_language_payload",
    "telegram_login_payload",
    "telegram_login_widget_config",
    "telegram_widget_config_payload",
]
