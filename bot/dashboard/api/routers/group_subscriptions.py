from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.config import get_settings
from bot.db.models import (
    GroupSubscriber,
    GroupSubscriptionSettings,
    SubscriptionPlan,
    PaymentRecord,
)
from bot.db.session import get_session
from bot.services.group_subscription_service import GroupSubscriptionService
from bot.services.group_payment_service import GroupPaymentService
from bot.services.telegram_webapp_auth import TelegramWebAppIdentity
from ..dependencies import get_identity, ensure_group_admin
from .auth_boundary import require_admin_boundary
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/groups/{group_id}/subscriptions", tags=["subscriptions"], dependencies=[Depends(require_admin_boundary)])
logger = logging.getLogger(__name__)


class SettingsUpdate(BaseModel):
    enabled: bool | None = None
    payment_mode: str | None = None
    default_currency: str | None = None
    auto_approve_manual_payments: bool | None = None
    auto_remove_expired: bool | None = None
    expiry_action: str | None = None
    grace_period_days: int | None = None
    reminder_days_before_expiry: int | None = None
    invite_link_expire_seconds: int | None = None
    invite_link_member_limit: int | None = None
    payment_instructions: str | None = None


class PlanCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    price_amount: int = Field(ge=0)
    currency: str = "USD"
    duration_days: int = Field(gt=0)


class PlanUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    price_amount: int | None = None
    currency: str | None = None
    duration_days: int | None = None
    enabled: bool | None = None


@router.get("/settings")
async def get_subscription_settings(
    group_id: int,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_group_admin(group_id, session, identity)
    settings = await GroupSubscriptionService(session).get_settings(group_id)
    return {
        "enabled": settings.enabled,
        "payment_mode": settings.payment_mode,
        "default_currency": settings.default_currency,
        "auto_approve_manual_payments": settings.auto_approve_manual_payments,
        "auto_remove_expired": settings.auto_remove_expired,
        "expiry_action": settings.expiry_action,
        "grace_period_days": settings.grace_period_days,
        "reminder_days_before_expiry": settings.reminder_days_before_expiry,
        "invite_link_expire_seconds": settings.invite_link_expire_seconds,
        "invite_link_member_limit": settings.invite_link_member_limit,
        "payment_instructions": settings.payment_instructions,
    }


@router.put("/settings")
async def update_subscription_settings(
    group_id: int,
    payload: SettingsUpdate,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_group_admin(group_id, session, identity)
    service = GroupSubscriptionService(session)
    settings = await service.get_settings(group_id)
    
    for key, value in payload.dict(exclude_unset=True).items():
        setattr(settings, key, value)
    
    await session.commit()
    return {"status": "ok"}


@router.get("/plans")
async def list_subscription_plans(
    group_id: int,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    await ensure_group_admin(group_id, session, identity)
    plans = await GroupSubscriptionService(session).list_plans(group_id, only_enabled=False)
    return [
        {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "price_amount": p.price_amount,
            "currency": p.currency,
            "duration_days": p.duration_days,
            "enabled": p.enabled,
        }
        for p in plans
    ]


@router.post("/plans")
async def create_subscription_plan(
    group_id: int,
    payload: PlanCreate,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_group_admin(group_id, session, identity)
    plan = await GroupSubscriptionService(session).create_plan(
        group_id, **payload.dict()
    )
    await session.commit()
    return {"status": "ok", "plan_id": plan.id}


@router.put("/plans/{plan_id}")
async def update_subscription_plan(
    group_id: int,
    plan_id: int,
    payload: PlanUpdate,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_group_admin(group_id, session, identity)
    stmt = select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id, SubscriptionPlan.group_id == group_id)
    plan = (await session.execute(stmt)).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    
    for key, value in payload.dict(exclude_unset=True).items():
        setattr(plan, key, value)
    
    await session.commit()
    return {"status": "ok"}


@router.get("/subscribers")
async def list_subscribers(
    group_id: int,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    await ensure_group_admin(group_id, session, identity)
    stmt = select(GroupSubscriber).where(GroupSubscriber.group_id == group_id)
    subscribers = (await session.execute(stmt)).scalars().all()
    return [
        {
            "id": s.id,
            "user_id": s.user_id,
            "username": s.username,
            "full_name": s.full_name,
            "status": s.status,
            "plan_id": s.plan_id,
            "starts_at": s.starts_at.isoformat() if s.starts_at else None,
            "expires_at": s.expires_at.isoformat() if s.expires_at else None,
        }
        for s in subscribers
    ]


@router.get("/payments")
async def list_payments(
    group_id: int,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    await ensure_group_admin(group_id, session, identity)
    stmt = select(PaymentRecord).where(PaymentRecord.group_id == group_id)
    payments = (await session.execute(stmt)).scalars().all()
    return [
        {
            "id": p.id,
            "user_id": p.user_id,
            "plan_id": p.plan_id,
            "provider": p.provider,
            "amount": p.amount,
            "currency": p.currency,
            "status": p.status,
            "provider_reference": p.provider_reference,
            "created_at": p.created_at.isoformat(),
        }
        for p in payments
    ]


@router.post("/payments/{payment_id}/mark-paid")
async def mark_payment_paid(
    group_id: int,
    payment_id: int,
    reference: str | None = None,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_group_admin(group_id, session, identity)
    stmt = select(PaymentRecord).where(PaymentRecord.id == payment_id, PaymentRecord.group_id == group_id)
    payment = (await session.execute(stmt)).scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
    await GroupPaymentService(session).mark_paid(payment_id, reference)
    await session.commit()
    return {"status": "ok"}


class StripeCheckoutRequest(BaseModel):
    plan_id: int
    success_url: str | None = None
    cancel_url: str | None = None


@router.post("/checkout/stripe", dependencies=[])
async def create_stripe_checkout(
    group_id: int,
    payload: StripeCheckoutRequest,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    service = GroupPaymentService(session)
    try:
        result = await service.create_stripe_checkout_session(
            group_id=group_id,
            user_id=identity.user_id,
            plan_id=payload.plan_id,
            success_url=payload.success_url or get_settings().webapp_url or "",
            cancel_url=payload.cancel_url or get_settings().webapp_url or "",
        )
        if not result:
            raise HTTPException(status_code=400, detail="Failed to create checkout session")
        return {"url": result["url"], "session_id": result["session_id"]}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/webhook/stripe", include_in_schema=False, dependencies=[])
async def stripe_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    try:
        result = await GroupPaymentService(session).handle_stripe_webhook(payload, signature)
        return {"status": result.get("status", "ok")}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
