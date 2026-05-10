from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from bot.db.models import (
    GroupSubscriber,
    GroupSubscriberStatus,
    GroupSubscriptionSettings,
    GroupExpiryAction,
)
from bot.services.group_subscription_service import GroupSubscriptionService

logger = logging.getLogger(__name__)


class GroupExpiryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.subscription_service = GroupSubscriptionService(session)

    async def check_expiring_subscriptions(self) -> None:
        """
        Finds subscriptions near expiry or already expired and takes action.
        """
        now = datetime.utcnow()
        
        # 1. Send reminders
        # Find active subscribers expiring in reminder_days_before_expiry
        # This needs more complex logic to avoid double-reminding.
        # For this MVP, we'll focus on the actual expiry enforcement.
        
        # 2. Process expired
        stmt = select(GroupSubscriber).where(
            and_(
                GroupSubscriber.status == GroupSubscriberStatus.ACTIVE,
                GroupSubscriber.expires_at < now
            )
        )
        expired_subscribers = (await self.session.execute(stmt)).scalars().all()
        
        for sub in expired_subscribers:
            await self.process_expiry(sub)
        
        await self.session.commit()

    async def process_expiry(self, subscriber: GroupSubscriber) -> None:
        settings = await self.subscription_service.get_settings(subscriber.group_id)
        
        grace_date = subscriber.expires_at + timedelta(days=settings.grace_period_days)
        now = datetime.utcnow()

        if now < grace_date:
            # Still in grace period
            return

        subscriber.status = GroupSubscriberStatus.EXPIRED
        
        await self.subscription_service.log_event(
            subscriber.group_id, 
            subscriber.user_id, 
            "subscription_expired", 
            {"subscriber_id": subscriber.id, "action": settings.expiry_action}
        )

        if settings.auto_remove_expired:
            if settings.expiry_action == GroupExpiryAction.REMOVE:
                await self._enforce_removal(subscriber)
            elif settings.expiry_action == GroupExpiryAction.RESTRICT:
                await self._enforce_restriction(subscriber)

    async def _enforce_removal(self, subscriber: GroupSubscriber) -> None:
        # Placeholder for Telegram remove logic (ban then unban)
        await self.subscription_service.log_event(
            subscriber.group_id, 
            subscriber.user_id, 
            "enforced_removal", 
            {"subscriber_id": subscriber.id}
        )

    async def _enforce_restriction(self, subscriber: GroupSubscriber) -> None:
        # Placeholder for Telegram restrict logic
        await self.subscription_service.log_event(
            subscriber.group_id, 
            subscriber.user_id, 
            "enforced_restriction", 
            {"subscriber_id": subscriber.id}
        )
