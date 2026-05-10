from __future__ import annotations

import logging
from typing import Any, Literal

from aiogram import Bot
from fastapi import APIRouter, Depends, HTTPException, Query, status
from datetime import datetime
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from bot.config import get_settings
from bot.dashboard.api.auth import extract_dashboard_identity
from bot.db.models import OwnerAuditLog, PromotionCode, PromotionCodeRedemption, SubscriptionRequest, SubscriptionStatus
from bot.db.session import get_session
from bot.services.menu_button_service import configure_private_chat_menu_button
...
from .routers._shared import (
    AccessGateUpdateRequest,
    RedeemCodeRequest,
)

class PromoCodeCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    plan: Literal["pro", "business"] = "pro"
    duration_days: int = Field(ge=1, le=3650)
    max_uses: int | None = Field(default=None, ge=1)
    expiry_date: datetime | None = Field(default=None)
    is_active: bool = True


class PromoCodeUpdateRequest(BaseModel):
    is_active: bool | None = None
    max_uses: int | None = Field(default=None, ge=1)
    expiry_date: datetime | None = Field(default=None)

from bot.services.owner_audit_service import log_owner_action
from bot.services.owner_service import OwnerService
from bot.services.private_access_requirement_service import PrivateAccessRequirementService
from bot.services.subscription_service import SubscriptionService, build_requester_status_notification
from bot.services.telegram_webapp_auth import TelegramWebAppIdentity
from bot.services.user_service import UserService

router = APIRouter(prefix="/webapp/owner", tags=["owner"])
logger = logging.getLogger(__name__)


class OwnerGroupActionResponse(BaseModel):
    status: str
    group: dict[str, Any]


class OwnerSubscription(BaseModel):
    id: int
    tg_user_id: int
    username: str | None
    full_name: str | None
    language_code: str | None
    message: str | None
    status: str
    response: str | None
    response_by: int | None
    created_at: str | None
    updated_at: str | None


class OwnerSubscriptionUpdateRequest(BaseModel):
    status: Literal["approved", "declined", "cancelled"] | None = None
    action: Literal["approve", "decline", "cancel"] | None = None
    plan: Literal["pro", "business"] | None = None
    response: str | None = None

    @property
    def normalized_status(self) -> Literal["approved", "declined", "cancelled"]:
        if self.status is not None:
            return self.status
        action_to_status = {
            "approve": "approved",
            "decline": "declined",
            "cancel": "cancelled",
        }
        if self.action is None:
            raise ValueError("Missing status")
        return action_to_status[self.action]


class OwnerAuditEntry(BaseModel):
    id: int
    actor_id: int
    action: str
    target_type: str
    target_id: str
    detail: dict[str, Any] | None
    created_at: str | None


class OwnerPrivateAccessGate(BaseModel):
    required_group_tg_ids: list[int]
    candidates: list[dict[str, Any]]


class OwnerPrivateAccessGateUpdateRequest(BaseModel):
    required_group_tg_ids: list[int] = []


def _serialize_subscription(request: SubscriptionRequest) -> dict[str, Any]:
    return {
        "id": request.id,
        "tg_user_id": request.tg_user_id,
        "username": request.username,
        "full_name": request.full_name,
        "language_code": request.language_code,
        "message": request.message,
        "status": request.status,
        "response": request.response,
        "response_by": request.response_by,
        "created_at": request.created_at.isoformat() if request.created_at else None,
        "updated_at": request.updated_at.isoformat() if request.updated_at else None,
    }


def _serialize_audit_entry(entry: OwnerAuditLog) -> dict[str, Any]:
    return {
        "id": entry.id,
        "actor_id": entry.actor_id,
        "action": entry.action,
        "target_type": entry.target_type,
        "target_id": entry.target_id,
        "detail": entry.detail,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


def _serialize_promo_code(promo: PromotionCode) -> dict[str, Any]:
    return {
        "id": promo.id,
        "code": promo.code,
        "plan": promo.plan,
        "duration_days": promo.duration_days,
        "max_uses": promo.max_uses,
        "used_count": promo.used_count,
        "is_active": promo.is_active,
        "expiry_date": promo.expiry_date.isoformat() if promo.expiry_date else None,
        "created_at": promo.created_at.isoformat() if promo.created_at else None,
    }


async def require_owner(
    identity: TelegramWebAppIdentity = Depends(extract_dashboard_identity),
    session: AsyncSession = Depends(get_session),
) -> TelegramWebAppIdentity:
    settings = get_settings()
    if identity.user_id not in settings.bot_owner_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is not a bot owner")

    user_service = UserService(session)
    full_name = " ".join(part for part in [identity.first_name, identity.last_name] if part).strip() or None
    await user_service.set_language(
        tg_user_id=identity.user_id,
        language_code=await user_service.resolve_language(identity.user_id, fallback=settings.default_language),
        username=identity.username,
        full_name=full_name,
    )
    return identity


@router.get("/stats")
async def owner_stats(
    _identity: TelegramWebAppIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> dict[str, int]:
    return await OwnerService(session).stats()


@router.get("/groups")
async def owner_groups(
    _identity: TelegramWebAppIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    return await OwnerService(session).list_groups()


@router.get("/agents")
async def owner_list_agents(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _identity: TelegramWebAppIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    return await OwnerService(session).list_all_agents(limit=limit, offset=offset)


@router.get("/users")
async def owner_list_users(
    _identity: TelegramWebAppIdentity = Depends(require_owner),
) -> list[dict[str, Any]]:
    settings = get_settings()
    return [
        {
            "user_id": user.user_id,
            "email": user.email,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role": "owner" if user.user_id in settings.bot_owner_ids else "admin",
        }
        for user in settings.dashboard_browser_users
    ]


@router.get("/groups/{group_id}")
async def owner_group_details(
    group_id: int,
    _identity: TelegramWebAppIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    payload = await OwnerService(session).get_group_details(group_id)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    return payload


@router.post("/groups/{group_id}/disable", response_model=OwnerGroupActionResponse)
async def owner_disable_group(
    group_id: int,
    identity: TelegramWebAppIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> OwnerGroupActionResponse:
    group = await OwnerService(session).disable_group(group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    await log_owner_action(
        session,
        actor_id=identity.user_id,
        action="disable_group",
        target_type="group",
        target_id=group_id,
    )
    return OwnerGroupActionResponse(status="disabled", group=group)


@router.post("/groups/{group_id}/leave", response_model=OwnerGroupActionResponse)
async def owner_leave_group(
    group_id: int,
    identity: TelegramWebAppIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> OwnerGroupActionResponse:
    service = OwnerService(session)
    payload = await service.get_group_details(group_id)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

    group = payload["group"]
    bot = Bot(token=get_settings().bot_token)
    try:
        await bot.leave_chat(group["tg_group_id"])
    except Exception as exc:
        logger.warning("owner_leave_group_failed", extra={"group_id": group_id, "error": str(exc)})
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to leave group") from exc
    finally:
        await bot.session.close()

    disabled_group = await service.disable_group(group_id)
    await log_owner_action(
        session,
        actor_id=identity.user_id,
        action="force_leave",
        target_type="group",
        target_id=group_id,
    )
    return OwnerGroupActionResponse(status="left", group=disabled_group or group)


@router.get("/subscriptions")
async def owner_subscriptions(
    _identity: TelegramWebAppIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> list[OwnerSubscription]:
    rows = await SubscriptionService(session).list_requests()
    return [_serialize_subscription(row) for row in rows]


@router.get("/private-access-gate")
async def owner_private_access_gate(
    _identity: TelegramWebAppIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> OwnerPrivateAccessGate:
    service = PrivateAccessRequirementService(session)
    return OwnerPrivateAccessGate(
        required_group_tg_ids=await service.list_required_group_tg_ids(),
        candidates=await service.list_candidate_groups(),
    )


@router.patch("/private-access-gate")
async def owner_update_private_access_gate(
    payload: OwnerPrivateAccessGateUpdateRequest,
    identity: TelegramWebAppIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> OwnerPrivateAccessGate:
    service = PrivateAccessRequirementService(session)
    candidate_tg_ids = {int(item["tg_group_id"]) for item in await service.list_candidate_groups()}
    requested = [value for value in payload.required_group_tg_ids if value in candidate_tg_ids]
    required_group_tg_ids = await service.replace_required_groups(requested)
    await log_owner_action(
        session,
        actor_id=identity.user_id,
        action="update_private_access_gate",
        target_type="private_access_gate",
        target_id="global",
        detail={"required_group_tg_ids": required_group_tg_ids},
    )
    return OwnerPrivateAccessGate(
        required_group_tg_ids=required_group_tg_ids,
        candidates=await service.list_candidate_groups(),
    )


@router.post("/subscriptions/{request_id}")
async def owner_update_subscription(
    request_id: int,
    payload: OwnerSubscriptionUpdateRequest,
    identity: TelegramWebAppIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> OwnerSubscription:
    try:
        status_enum = SubscriptionStatus(payload.normalized_status)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    request = await SubscriptionService(session).update_request_status(
        request_id=request_id,
        status=status_enum,
        response=payload.response,
        responder_id=identity.user_id,
    )
    if request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription request not found")

    if status_enum is SubscriptionStatus.APPROVED and payload.plan:
        request.plan = payload.plan
        await session.commit()

    if status_enum is SubscriptionStatus.APPROVED:
        action = "approve_subscription"
    elif status_enum is SubscriptionStatus.CANCELLED:
        action = "cancel_subscription"
    else:
        action = "decline_subscription"
    await log_owner_action(
        session,
        actor_id=identity.user_id,
        action=action,
        target_type="subscription",
        target_id=request_id,
        detail={"status": status_enum.value, "response": payload.response},
    )

    bot = Bot(token=get_settings().bot_token)
    try:
        await configure_private_chat_menu_button(
            bot=bot,
            user_id=request.tg_user_id,
            enabled=status_enum is SubscriptionStatus.APPROVED,
        )
        await bot.send_message(
            request.tg_user_id,
            build_requester_status_notification(status=status_enum, response=payload.response),
        )
    except Exception as exc:
        logger.warning(
            "owner_update_subscription_notify_failed",
            extra={"request_id": request_id, "user_id": request.tg_user_id, "error": str(exc)},
        )
    finally:
        await bot.session.close()
    return _serialize_subscription(request)


@router.get("/audit-log")
async def owner_audit_log(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _identity: TelegramWebAppIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> list[OwnerAuditEntry]:
    rows = (
        await session.execute(
            select(OwnerAuditLog)
            .order_by(desc(OwnerAuditLog.created_at), desc(OwnerAuditLog.id))
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return [_serialize_audit_entry(row) for row in rows]


@router.get("/promo-codes")
async def owner_list_promo_codes(
    limit: int = Query(default=100, ge=1, le=500),
    _identity: TelegramWebAppIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(PromotionCode).order_by(desc(PromotionCode.created_at)).limit(limit)
        )
    ).scalars().all()
    return [_serialize_promo_code(row) for row in rows]


@router.post("/promo-codes")
async def owner_create_promo_code(
    payload: PromoCodeCreateRequest,
    identity: TelegramWebAppIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    # Check if code already exists
    stmt = select(PromotionCode).where(PromotionCode.code == payload.code.strip().upper())
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Promotion code already exists")

    promo = PromotionCode(
        code=payload.code.strip().upper(),
        plan=payload.plan,
        duration_days=payload.duration_days,
        max_uses=payload.max_uses,
        expiry_date=payload.expiry_date,
        is_active=payload.is_active,
    )
    session.add(promo)
    await session.commit()
    await session.refresh(promo)
    
    await log_owner_action(
        session,
        actor_id=identity.user_id,
        action="create_promo_code",
        target_type="promo_code",
        target_id=promo.id,
        detail={
            "code": promo.code,
            "duration_days": promo.duration_days,
            "max_uses": promo.max_uses,
        },
    )
    return _serialize_promo_code(promo)


@router.patch("/promo-codes/{promo_code_id}")
async def owner_update_promo_code(
    promo_code_id: int,
    payload: PromoCodeUpdateRequest,
    identity: TelegramWebAppIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    promo = (await session.execute(select(PromotionCode).where(PromotionCode.id == promo_code_id))).scalar_one_or_none()
    if not promo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promotion code not found")
        
    if payload.is_active is not None:
        promo.is_active = payload.is_active
    if payload.max_uses is not None:
        promo.max_uses = payload.max_uses
    if payload.expiry_date is not None:
        promo.expiry_date = payload.expiry_date
        
    await session.commit()
    await session.refresh(promo)
    
    await log_owner_action(
        session,
        actor_id=identity.user_id,
        action="update_promo_code",
        target_type="promo_code",
        target_id=promo_code_id,
        detail=payload.model_dump(exclude_none=True),
    )
    return _serialize_promo_code(promo)


@router.delete("/promo-codes/{promo_code_id}")
async def owner_delete_promo_code(
    promo_code_id: int,
    identity: TelegramWebAppIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    promo = (await session.execute(select(PromotionCode).where(PromotionCode.id == promo_code_id))).scalar_one_or_none()
    if not promo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promotion code not found")
        
    await session.delete(promo)
    await session.commit()
    
    await log_owner_action(
        session,
        actor_id=identity.user_id,
        action="delete_promo_code",
        target_type="promo_code",
        target_id=promo_code_id,
    )
    return {"status": "ok"}
