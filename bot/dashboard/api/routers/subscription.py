from __future__ import annotations

from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import get_settings
from bot.db.models import SubscriptionRequest, SubscriptionStatus
from bot.db.session import get_session
from bot.services.promotion_service import PromotionError, PromotionService
from bot.services.telegram_webapp_auth import TelegramWebAppIdentity

from ..dependencies import get_identity
from .auth_boundary import require_agents_boundary, require_any_boundary, require_admin_boundary
from ._shared import RedeemCodeRequest

router = APIRouter(tags=["subscription"])

AGENT_STRIPE_PLANS: dict[str, dict[str, Any]] = {
    "pro": {"label": "Pro", "amount": 2900, "duration_days": 30},
    "business": {"label": "Business", "amount": 7900, "duration_days": 30},
}


class AgentStripeCheckoutRequest(BaseModel):
    plan: Literal["pro", "business"]
    success_url: str | None = None
    cancel_url: str | None = None


def _resolve_bot_kind(request: Request) -> str | None:
    boundary = request.headers.get("X-App-Boundary", "").strip().lower()
    if boundary in ("admin", "agents"):
        return boundary
    return None


def _append_query_params(url: str, params: dict[str, str]) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(params)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _fallback_agents_url() -> str:
    settings = get_settings()
    return settings.agents_webapp_url or settings.webapp_url or settings.dashboard_url or ""


@router.get("/api/agents/subscription/status", dependencies=[Depends(require_any_boundary(["admin", "agents"]))])
@router.get("/webapp/agents/subscription/status", dependencies=[Depends(require_any_boundary(["admin", "agents"]))])
async def webapp_subscription_status(
    request: Request,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    bot_kind = _resolve_bot_kind(request)
    stmt = select(SubscriptionRequest).where(
        SubscriptionRequest.tg_user_id == identity.user_id,
        SubscriptionRequest.status == SubscriptionStatus.APPROVED.value,
    )
    if bot_kind:
        stmt = stmt.where(
            or_(
                SubscriptionRequest.bot_kind == bot_kind,
                SubscriptionRequest.bot_kind.is_(None),
            )
        )
    stmt = stmt.order_by(SubscriptionRequest.id.desc()).limit(1)
    subscription = (await session.execute(stmt)).scalar_one_or_none()

    if not subscription:
        return {"status": "inactive", "plan": None, "expires_at": None, "bot_kind": bot_kind}

    return {
        "status": "active",
        "plan": subscription.plan,
        "bot_kind": subscription.bot_kind or bot_kind,
        "expires_at": subscription.expires_at.isoformat() if subscription.expires_at else None,
    }


@router.post("/api/agents/subscription/redeem", dependencies=[Depends(require_agents_boundary)])
@router.post("/webapp/agents/subscription/redeem", dependencies=[Depends(require_agents_boundary)])
async def webapp_redeem_promo(
    payload: RedeemCodeRequest,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        subscription = await PromotionService(session).redeem_code(
            tg_user_id=identity.user_id,
            code=payload.code,
            bot_kind="agents",
        )
    except PromotionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return {
        "success": True,
        "status": "active",
        "plan": subscription.plan,
        "bot_kind": subscription.bot_kind or "agents",
        "expires_at": subscription.expires_at.isoformat() if subscription.expires_at else None,
        "message": "Promotion code redeemed successfully.",
    }


@router.post("/api/agents/subscription/checkout/stripe", dependencies=[Depends(require_agents_boundary)])
@router.post("/webapp/agents/subscription/checkout/stripe", dependencies=[Depends(require_agents_boundary)])
async def webapp_agents_stripe_checkout(
    payload: AgentStripeCheckoutRequest,
    identity: TelegramWebAppIdentity = Depends(get_identity),
) -> dict[str, str]:
    settings = get_settings()
    if not settings.stripe_api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Stripe is not configured. Set STRIPE_API_KEY.",
        )

    success_url = payload.success_url or _fallback_agents_url()
    cancel_url = payload.cancel_url or _fallback_agents_url()
    if not success_url or not cancel_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Stripe checkout requires success_url and cancel_url.",
        )

    plan = AGENT_STRIPE_PLANS[payload.plan]
    try:
        import stripe as stripe_lib

        stripe_lib.api_key = settings.stripe_api_key
        checkout = stripe_lib.checkout.Session.create(
            mode="payment",
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "product_data": {
                            "name": f"MadarAppBot Agents {plan['label']}",
                            "description": f"{plan['duration_days']}-day access to agents features",
                        },
                        "unit_amount": plan["amount"],
                    },
                    "quantity": 1,
                }
            ],
            metadata={
                "payment_type": "agent_subscription",
                "tg_user_id": str(identity.user_id),
                "plan": payload.plan,
                "duration_days": str(plan["duration_days"]),
                "bot_kind": "agents",
            },
            success_url=_append_query_params(success_url, {"paid": "1", "plan": payload.plan}),
            cancel_url=cancel_url,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return {"url": checkout.url, "session_id": checkout.id}


__all__ = ["router"]
