from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import get_settings
from bot.db.models import (
    GroupPaymentMode,
    GroupPaymentStatus,
    PaymentRecord,
    SubscriptionPlan,
    SubscriptionRequest,
    SubscriptionStatus,
)
from bot.services.group_subscription_service import GroupSubscriptionService

logger = logging.getLogger(__name__)


class GroupPaymentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.subscription_service = GroupSubscriptionService(session)

    async def create_manual_payment(self, group_id: int, user_id: int, plan_id: int) -> PaymentRecord:
        from sqlalchemy import select
        plan_stmt = select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id)
        plan = (await self.session.execute(plan_stmt)).scalar_one()

        payment = PaymentRecord(
            group_id=group_id,
            user_id=user_id,
            plan_id=plan_id,
            provider=GroupPaymentMode.MANUAL,
            amount=plan.price_amount,
            currency=plan.currency,
            status=GroupPaymentStatus.PENDING,
        )
        self.session.add(payment)
        await self.session.flush()
        await self.subscription_service.log_event(
            group_id, user_id, "manual_payment_created", {"payment_id": payment.id},
        )
        return payment

    async def mark_paid(self, payment_id: int, reference: str | None = None) -> PaymentRecord | None:
        return await self.subscription_service.confirm_payment(payment_id, reference)

    async def create_stripe_checkout_session(
        self, group_id: int, user_id: int, plan_id: int, success_url: str, cancel_url: str,
    ) -> dict | None:
        settings = get_settings()
        if not settings.stripe_api_key:
            raise ValueError("Stripe is not configured. Set STRIPE_API_KEY.")

        from sqlalchemy import select
        plan_stmt = select(SubscriptionPlan).where(
            SubscriptionPlan.id == plan_id, SubscriptionPlan.group_id == group_id,
        )
        plan = (await self.session.execute(plan_stmt)).scalar_one_or_none()
        if not plan:
            raise ValueError("Subscription plan not found.")
        if not plan.enabled:
            raise ValueError("Plan is disabled.")

        import stripe as stripe_lib
        stripe_lib.api_key = settings.stripe_api_key

        if plan.stripe_price_id:
            session = stripe_lib.checkout.Session.create(
                mode="subscription" if plan.duration_days >= 30 else "payment",
                line_items=[{"price": plan.stripe_price_id, "quantity": 1}],
                metadata={
                    "group_id": str(group_id),
                    "user_id": str(user_id),
                    "plan_id": str(plan_id),
                    "payment_type": "group_subscription",
                },
                success_url=success_url + "?" + urlencode({"paid": "1"}),
                cancel_url=cancel_url,
            )
        else:
            session = stripe_lib.checkout.Session.create(
                mode="subscription" if plan.duration_days >= 30 else "payment",
                line_items=[{
                    "price_data": {
                        "currency": plan.currency.lower() or "usd",
                        "product_data": {
                            "name": plan.name or "Group Access Plan",
                            "description": plan.description or f"{plan.duration_days}-day access",
                        },
                        "unit_amount": plan.price_amount,
                        "recurring": {"interval": "month"} if plan.duration_days >= 30 else None,
                    },
                    "quantity": 1,
                }],
                metadata={
                    "group_id": str(group_id),
                    "user_id": str(user_id),
                    "plan_id": str(plan_id),
                    "payment_type": "group_subscription",
                },
                success_url=success_url + "?" + urlencode({"paid": "1"}),
                cancel_url=cancel_url,
            )

        return {"url": session.url, "session_id": session.id}

    async def handle_stripe_webhook(self, payload: bytes, signature: str) -> dict:
        import stripe as stripe_lib

        settings = get_settings()
        if not settings.stripe_webhook_secret:
            raise ValueError("Stripe webhook not configured. Set STRIPE_WEBHOOK_SECRET.")

        try:
            event = stripe_lib.Webhook.construct_event(
                payload, signature, settings.stripe_webhook_secret,
            )
        except (ValueError, stripe_lib.error.SignatureVerificationError) as exc:
            logger.error("stripe_webhook_verification_failed", error=str(exc))
            raise ValueError("Invalid webhook signature") from exc

        if event["type"] == "checkout.session.completed":
            return await self._handle_checkout_completed(event["data"]["object"])
        if event["type"] == "checkout.session.expired":
            return {"status": "ignored", "event": event["type"]}

        logger.info("stripe_webhook_unhandled_event", event_type=event["type"])
        return {"status": "ok", "event": event["type"]}

    async def _handle_checkout_completed(self, session_data: dict) -> dict:
        metadata = session_data.get("metadata", {})
        if metadata.get("payment_type") == "agent_subscription":
            return await self._handle_agent_subscription_checkout_completed(session_data)

        group_id = int(metadata.get("group_id", 0))
        user_id = int(metadata.get("user_id", 0))
        plan_id = int(metadata.get("plan_id", 0))
        session_id = session_data.get("id", "")
        amount = session_data.get("amount_total", 0)
        currency = session_data.get("currency", "usd")

        if not group_id or not user_id or not plan_id:
            logger.warning("stripe_webhook_missing_metadata", metadata=metadata)
            return {"status": "missing_metadata"}

        from sqlalchemy import select
        existing = (await self.session.execute(
            select(PaymentRecord).where(
                PaymentRecord.provider == GroupPaymentMode.STRIPE,
                PaymentRecord.provider_reference == session_id,
            )
        )).scalar_one_or_none()
        if existing:
            return {"status": "already_processed", "payment_id": existing.id}

        payment = PaymentRecord(
            group_id=group_id,
            user_id=user_id,
            plan_id=plan_id,
            provider=GroupPaymentMode.STRIPE,
            amount=amount,
            currency=currency.upper(),
            status=GroupPaymentStatus.PAID,
            provider_reference=session_id,
            metadata_json={"stripe_session": session_id},
        )
        self.session.add(payment)
        await self.session.flush()
        await self.subscription_service.activate_subscription(
            group_id, user_id, plan_id,
            provider=GroupPaymentMode.STRIPE,
            reference=session_id,
        )
        await self.session.commit()
        return {"status": "activated", "payment_id": payment.id}

    async def _handle_agent_subscription_checkout_completed(self, session_data: dict) -> dict:
        metadata = session_data.get("metadata", {})
        try:
            tg_user_id = int(metadata.get("tg_user_id", 0))
            duration_days = int(metadata.get("duration_days", 30))
        except (TypeError, ValueError):
            tg_user_id = 0
            duration_days = 30

        plan = str(metadata.get("plan") or "pro")
        if plan not in {"pro", "business"}:
            plan = "pro"
        if tg_user_id <= 0:
            logger.warning("stripe_agent_subscription_missing_user", metadata=metadata)
            return {"status": "missing_metadata"}

        now = datetime.now(timezone.utc)
        duration = timedelta(days=max(duration_days, 1))
        session_id = str(session_data.get("id") or "")

        from sqlalchemy import select

        stmt = (
            select(SubscriptionRequest)
            .where(
                SubscriptionRequest.tg_user_id == tg_user_id,
                SubscriptionRequest.status == SubscriptionStatus.APPROVED.value,
            )
            .order_by(SubscriptionRequest.id.desc())
            .limit(1)
        )
        subscription = (await self.session.execute(stmt)).scalar_one_or_none()

        if subscription is None:
            subscription = SubscriptionRequest(
                tg_user_id=tg_user_id,
                status=SubscriptionStatus.APPROVED.value,
                plan=plan,
                bot_kind="agents",
                expires_at=now + duration,
                message=f"Stripe checkout: {session_id}",
            )
            self.session.add(subscription)
        elif subscription.expires_at is not None:
            current_expires_at = subscription.expires_at
            if current_expires_at.tzinfo is None:
                current_expires_at = current_expires_at.replace(tzinfo=timezone.utc)
            start_from = max(current_expires_at, now)
            subscription.expires_at = start_from + duration
            subscription.plan = plan
            subscription.bot_kind = "agents"
            subscription.message = subscription.message or f"Stripe checkout: {session_id}"
        else:
            subscription.plan = plan
            subscription.bot_kind = "agents"

        await self.session.commit()
        await self.session.refresh(subscription)
        return {"status": "activated", "subscription_request_id": subscription.id}
