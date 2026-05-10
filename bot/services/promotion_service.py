from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import PromotionCode, PromotionCodeRedemption, SubscriptionRequest, SubscriptionStatus

logger = logging.getLogger(__name__)


class PromotionError(Exception):
    """Base class for promotion-related errors."""


class PromotionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def redeem_code(self, *, tg_user_id: int, code: str, bot_kind: str | None = None) -> SubscriptionRequest:
        """
        Redeem a promotion code for a user.
        If bot_kind is provided, the promo code's bot_kind must match (or be null/any).
        """
        normalized_code = code.strip().upper()

        stmt = select(PromotionCode).where(PromotionCode.code == normalized_code).with_for_update()
        promo = (await self.session.execute(stmt)).scalar_one_or_none()

        if not promo:
            raise PromotionError("Invalid promotion code.")

        if bot_kind and promo.bot_kind and promo.bot_kind != bot_kind:
            raise PromotionError("This promotion code is not valid for this bot.")
            
        # 2. Validate active, not expired, and under max_uses
        now = datetime.now(timezone.utc)
        if not promo.is_active:
            raise PromotionError("This promotion code is no longer active.")
        if promo.expiry_date and promo.expiry_date < now:
            raise PromotionError("This promotion code has expired.")
        if promo.max_uses is not None and promo.used_count >= promo.max_uses:
            raise PromotionError("This promotion code has reached its maximum usage limit.")
            
        # 3. Check if user has already redeemed it
        history_stmt = select(PromotionCodeRedemption).where(
            PromotionCodeRedemption.promo_code_id == promo.id,
            PromotionCodeRedemption.tg_user_id == tg_user_id,
        )
        existing_redemption = (await self.session.execute(history_stmt)).scalar_one_or_none()
        if existing_redemption:
            # If the redemption still has an active subscription, return it as success
            if existing_redemption.subscription_request_id:
                sub_stmt = select(SubscriptionRequest).where(
                    SubscriptionRequest.id == existing_redemption.subscription_request_id,
                    SubscriptionRequest.status == SubscriptionStatus.APPROVED.value,
                )
                existing_sub = (await self.session.execute(sub_stmt)).scalar_one_or_none()
                if existing_sub and (existing_sub.expires_at is None or existing_sub.expires_at > now):
                    return existing_sub
            # Subscription expired or missing — allow re-redeeming
            
        # 4. Find active approved subscription for user
        sub_stmt = select(SubscriptionRequest).where(
            SubscriptionRequest.tg_user_id == tg_user_id,
            SubscriptionRequest.status == SubscriptionStatus.APPROVED.value,
        ).order_by(SubscriptionRequest.id.desc()).limit(1)
        subscription = (await self.session.execute(sub_stmt)).scalar_one_or_none()
        
        duration = timedelta(days=promo.duration_days)
        
        if subscription:
            # If lifetime subscription exists, do not shorten it.
            if subscription.expires_at is None:
                subscription.plan = promo.plan
                subscription.promo_code_id = promo.id
            else:
                # Extend from max(existing expires_at, now)
                start_from = max(subscription.expires_at, now)
                subscription.expires_at = start_from + duration
                subscription.promo_code_id = promo.id
                subscription.plan = promo.plan
            # Ensure bot_kind is set for existing subscriptions
            if not subscription.bot_kind:
                subscription.bot_kind = bot_kind or promo.bot_kind
        else:
            # No active subscription, create a new approved one
            subscription = SubscriptionRequest(
                tg_user_id=tg_user_id,
                status=SubscriptionStatus.APPROVED.value,
                expires_at=now + duration,
                promo_code_id=promo.id,
                plan=promo.plan,
                bot_kind=promo.bot_kind or bot_kind,
                message=f"Redeemed promo code: {normalized_code}",
            )
            self.session.add(subscription)
            await self.session.flush()

        # 5. Record redemption (or update existing to avoid unique constraint violation)
        if existing_redemption:
            existing_redemption.subscription_request_id = subscription.id
        else:
            redemption = PromotionCodeRedemption(
                promo_code_id=promo.id,
                tg_user_id=tg_user_id,
                subscription_request_id=subscription.id,
            )
            self.session.add(redemption)
        
        # 6. Increment used_count
        promo.used_count += 1
        
        await self.session.commit()
        await self.session.refresh(subscription)
        return subscription
