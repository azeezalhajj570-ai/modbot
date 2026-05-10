"""Group subscription management with Stripe integration."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import get_settings
from bot.db.models import (
    GroupPaymentMode,
    GroupPaymentStatus,
    GroupSubscriber,
    GroupSubscriberStatus,
    GroupSubscriptionSettings,
    PaymentRecord,
    SubscriptionEvent,
    SubscriptionPlan,
)

logger = logging.getLogger(__name__)


class GroupSubscriptionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_settings(self, group_id: int) -> GroupSubscriptionSettings:
        stmt = select(GroupSubscriptionSettings).where(GroupSubscriptionSettings.group_id == group_id)
        settings = (await self.session.execute(stmt)).scalar_one_or_none()
        if not settings:
            settings = GroupSubscriptionSettings(group_id=group_id)
            self.session.add(settings)
            await self.session.flush()
        return settings

    async def create_plan(
        self, group_id: int, name: str, price_amount: int, duration_days: int, **kwargs,
    ) -> SubscriptionPlan:
        description = kwargs.pop("description", None)
        currency = kwargs.pop("currency", "USD")

        plan = SubscriptionPlan(
            group_id=group_id,
            name=name,
            description=description,
            price_amount=price_amount,
            currency=currency,
            duration_days=duration_days,
            **kwargs,
        )
        self.session.add(plan)

        settings = get_settings()
        if settings.stripe_api_key:
            try:
                import stripe as stripe_lib
                stripe_lib.api_key = settings.stripe_api_key
                product = stripe_lib.Product.create(
                    name=name,
                    description=description or f"{duration_days}-day access plan",
                    metadata={"group_id": str(group_id)},
                )
                price = stripe_lib.Price.create(
                    product=product.id,
                    unit_amount=price_amount,
                    currency=currency.lower() or "usd",
                    recurring={"interval": "month"} if duration_days >= 30 else None,
                    metadata={"group_id": str(group_id), "plan_name": name},
                )
                plan.stripe_price_id = price.id
                logger.info("stripe_price_created", plan_id=plan.id, price_id=price.id)
            except Exception as exc:
                logger.warning("stripe_price_creation_failed", plan=name, error=str(exc))

        await self.session.flush()
        await self.log_event(group_id, None, "plan_created", {"plan_id": plan.id, "name": name})
        return plan

    async def list_plans(self, group_id: int, only_enabled: bool = True) -> list[SubscriptionPlan]:
        stmt = select(SubscriptionPlan).where(SubscriptionPlan.group_id == group_id)
        if only_enabled:
            stmt = stmt.where(SubscriptionPlan.enabled == True)
        return list((await self.session.execute(stmt)).scalars().all())

    async def request_access(self, group_id: int, user_id: int, plan_id: int, **user_info: Any) -> GroupSubscriber:
        # Check if already has active/pending subscription
        existing_stmt = select(GroupSubscriber).where(
            and_(
                GroupSubscriber.group_id == group_id,
                GroupSubscriber.user_id == user_id,
                GroupSubscriber.status.in_([GroupSubscriberStatus.ACTIVE, GroupSubscriberStatus.PENDING])
            )
        )
        existing = (await self.session.execute(existing_stmt)).scalar_one_or_none()
        if existing:
            return existing

        subscriber = GroupSubscriber(
            group_id=group_id,
            user_id=user_id,
            plan_id=plan_id,
            status=GroupSubscriberStatus.PENDING,
            **user_info
        )
        self.session.add(subscriber)
        await self.session.flush()
        await self.log_event(group_id, user_id, "access_requested", {"plan_id": plan_id})
        return subscriber

    async def confirm_payment(self, payment_id: int, reference: str | None = None) -> PaymentRecord | None:
        stmt = select(PaymentRecord).where(PaymentRecord.id == payment_id)
        payment = (await self.session.execute(stmt)).scalar_one_or_none()
        if not payment or payment.status == GroupPaymentStatus.PAID:
            return payment

        payment.status = GroupPaymentStatus.PAID
        if reference:
            payment.provider_reference = reference
        
        await self.activate_subscription(payment.group_id, payment.user_id, payment.plan_id, payment.provider, payment.provider_reference)
        await self.log_event(payment.group_id, payment.user_id, "payment_confirmed", {"payment_id": payment_id})
        return payment

    async def activate_subscription(self, group_id: int, user_id: int, plan_id: int, provider: str, reference: str | None) -> GroupSubscriber:
        plan_stmt = select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id)
        plan = (await self.session.execute(plan_stmt)).scalar_one()

        stmt = select(GroupSubscriber).where(
            and_(
                GroupSubscriber.group_id == group_id,
                GroupSubscriber.user_id == user_id,
                GroupSubscriber.status.in_([GroupSubscriberStatus.ACTIVE, GroupSubscriberStatus.PENDING])
            )
        )
        subscriber = (await self.session.execute(stmt)).scalar_one_or_none()
        
        now = datetime.utcnow()
        if not subscriber:
            subscriber = GroupSubscriber(group_id=group_id, user_id=user_id, plan_id=plan_id)
            self.session.add(subscriber)

        subscriber.status = GroupSubscriberStatus.ACTIVE
        subscriber.starts_at = now
        subscriber.expires_at = now + timedelta(days=plan.duration_days)
        subscriber.payment_provider = provider
        subscriber.payment_reference = reference
        
        await self.session.flush()
        await self.log_event(group_id, user_id, "subscription_activated", {
            "plan_id": plan_id,
            "expires_at": subscriber.expires_at.isoformat()
        })
        return subscriber

    async def log_event(self, group_id: int, user_id: int | None, event_type: str, details: dict[str, Any]) -> None:
        event = SubscriptionEvent(
            group_id=group_id,
            user_id=user_id,
            event_type=event_type,
            details_json=details
        )
        self.session.add(event)
        await self.session.flush()
