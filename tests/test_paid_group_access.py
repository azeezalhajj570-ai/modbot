from __future__ import annotations

import pytest
from datetime import datetime, timedelta
from sqlalchemy import select
from bot.db.models import (
    Group,
    SubscriptionPlan,
    GroupSubscriber,
    GroupSubscriberStatus,
    PaymentRecord,
    GroupPaymentStatus,
    GroupSubscriptionSettings,
    SubscriptionEvent,
)
from bot.services.group_subscription_service import GroupSubscriptionService
from bot.services.group_payment_service import GroupPaymentService
from bot.services.group_expiry_service import GroupExpiryService

@pytest.mark.asyncio
async def test_paid_access_full_flow(db_session):
    # 1. Setup group and settings
    group = Group(tg_group_id=12345, title="Private VIP")
    db_session.add(group)
    await db_session.flush()
    
    service = GroupSubscriptionService(db_session)
    settings = await service.get_settings(group.id)
    assert settings.enabled is False
    
    settings.enabled = True
    await db_session.commit()
    
    # 2. Create a plan
    plan = await service.create_plan(
        group_id=group.id,
        name="VIP Monthly",
        price_amount=2900,  # $29.00
        duration_days=30
    )
    assert plan.id is not None
    
    # 3. User requests access
    user_id = 999
    subscriber = await service.request_access(
        group_id=group.id,
        user_id=user_id,
        plan_id=plan.id,
        username="testuser",
        full_name="Test User"
    )
    assert subscriber.status == GroupSubscriberStatus.PENDING
    
    # 4. Create manual payment
    payment_service = GroupPaymentService(db_session)
    payment = await payment_service.create_manual_payment(
        group_id=group.id,
        user_id=user_id,
        plan_id=plan.id
    )
    assert payment.status == GroupPaymentStatus.PENDING
    assert payment.amount == 2900
    
    # 5. Confirm payment
    await payment_service.mark_paid(payment.id, reference="CASH123")
    
    # 6. Verify active subscription
    await db_session.refresh(subscriber)
    assert subscriber.status == GroupSubscriberStatus.ACTIVE
    assert subscriber.payment_reference == "CASH123"
    assert subscriber.expires_at > datetime.utcnow() + timedelta(days=29)
    
    # 7. Test expiry logic
    subscriber.expires_at = datetime.utcnow() - timedelta(hours=1)
    await db_session.commit()
    
    expiry_service = GroupExpiryService(db_session)
    # With grace period of 3 days, it should NOT expire yet
    await expiry_service.check_expiring_subscriptions()
    await db_session.refresh(subscriber)
    assert subscriber.status == GroupSubscriberStatus.ACTIVE
    
    # Move past grace period
    subscriber.expires_at = datetime.utcnow() - timedelta(days=4)
    await db_session.commit()
    
    await expiry_service.check_expiring_subscriptions()
    await db_session.refresh(subscriber)
    assert subscriber.status == GroupSubscriberStatus.EXPIRED
    
    # Verify events
    events_stmt = select(SubscriptionEvent).where(SubscriptionEvent.group_id == group.id)
    events = (await db_session.execute(events_stmt)).scalars().all()
    event_types = [e.event_type for e in events]
    assert "plan_created" in event_types
    assert "access_requested" in event_types
    assert "subscription_activated" in event_types
    assert "subscription_expired" in event_types

@pytest.mark.asyncio
async def test_subscription_settings_defaults(db_session):
    group = Group(tg_group_id=111, title="Test Group")
    db_session.add(group)
    await db_session.flush()
    
    service = GroupSubscriptionService(db_session)
    settings = await service.get_settings(group.id)
    
    assert settings.enabled is False
    assert settings.payment_mode == "manual_payment"
    assert settings.expiry_action == "review"
    assert settings.grace_period_days == 3

@pytest.mark.asyncio
async def test_join_request_paid_check(db_session, fake_bot, telegram_update_factory, monkeypatch):
    from aiogram.types import ChatJoinRequest, User as TGUser, Chat
    from bot.handlers.join_request import on_chat_join_request
    import bot.handlers.join_request
    
    group = Group(tg_group_id=-100123456789, title="Paid Group")
    db_session.add(group)
    await db_session.flush()
    
    # Mock resolve_group_by_tg_id to return our test group
    async def mock_resolve_group(session, tg_id):
        return group
    monkeypatch.setattr(bot.handlers.join_request, "resolve_group_by_tg_id", mock_resolve_group)

    # Mock SessionLocal to return our test session
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def mock_session_local():
        yield db_session
    monkeypatch.setattr(bot.handlers.join_request, "SessionLocal", mock_session_local)
    
    service = GroupSubscriptionService(db_session)
    settings = await service.get_settings(group.id)
    settings.enabled = True
    await db_session.commit()
    
    # Mock update
    user = TGUser(id=777, is_bot=False, first_name="Payer")
    chat = Chat(id=-100123456789, type="supergroup", title="Paid Group")
    event = ChatJoinRequest(
        chat=chat,
        from_user=user,
        date=datetime.utcnow(),
        user_chat_id=777,
        invite_link=None
    )
    event._bot = fake_bot
    
    # 1. No subscription -> should notify user and return (not approved)
    await on_chat_join_request(event)
    
    sent_texts = [m[1] for m in fake_bot.sent_messages]
    assert any("requires a paid subscription" in t for m, t in fake_bot.sent_messages)
    assert len(fake_bot.sent_messages) > 0
    
    # 2. Active subscription -> should proceed to regular join checks
    # (In this test, it will return because no 'join_request_verify' setting)
    plan = await service.create_plan(group.id, "Plan", 100, 30)
    await service.activate_subscription(group.id, 777, plan.id, "manual", "REF")
    await db_session.commit()
    
    fake_bot.sent_messages.clear()
    await on_chat_join_request(event)
    
    # Should not send the "requires paid" message again
    assert not any("requires a paid subscription" in t for m, t in fake_bot.sent_messages)
