from __future__ import annotations

import pytest
from datetime import datetime, timedelta
from sqlalchemy import select

from bot.db.models import SubscriptionRequest, SubscriptionStatus
from bot.services.group_payment_service import GroupPaymentService
from bot.services.subscription_service import SubscriptionService


@pytest.mark.asyncio
async def test_has_active_subscription_true_when_approved_lifetime(db_session) -> None:
    uid = 99_001
    db_session.add(
        SubscriptionRequest(
            tg_user_id=uid,
            status=SubscriptionStatus.APPROVED.value,
            expires_at=None,
        )
    )
    await db_session.commit()

    assert await SubscriptionService(db_session).has_active_subscription(tg_user_id=uid) is True


@pytest.mark.asyncio
async def test_has_active_subscription_true_when_approved_future(db_session) -> None:
    uid = 99_003
    db_session.add(
        SubscriptionRequest(
            tg_user_id=uid,
            status=SubscriptionStatus.APPROVED.value,
            expires_at=datetime.utcnow() + timedelta(days=1),
        )
    )
    await db_session.commit()

    assert await SubscriptionService(db_session).has_active_subscription(tg_user_id=uid) is True


@pytest.mark.asyncio
async def test_has_active_subscription_false_when_approved_past(db_session) -> None:
    uid = 99_004
    db_session.add(
        SubscriptionRequest(
            tg_user_id=uid,
            status=SubscriptionStatus.APPROVED.value,
            expires_at=datetime.utcnow() - timedelta(days=1),
        )
    )
    await db_session.commit()

    assert await SubscriptionService(db_session).has_active_subscription(tg_user_id=uid) is False


@pytest.mark.asyncio
async def test_approve_supersedes_other_approved_for_same_user(db_session) -> None:
    uid = 99_010
    old = SubscriptionRequest(
        tg_user_id=uid,
        username="u",
        full_name="Old",
        status=SubscriptionStatus.APPROVED.value,
        response="Welcome",
    )
    new = SubscriptionRequest(
        tg_user_id=uid,
        username="u",
        full_name="New",
        status=SubscriptionStatus.PENDING.value,
    )
    db_session.add_all([old, new])
    await db_session.commit()
    new_id = new.id
    old_id = old.id

    await SubscriptionService(db_session).update_request_status(
        request_id=new_id,
        status=SubscriptionStatus.APPROVED,
        response="Latest",
        responder_id=7000,
    )

    old_row = (
        await db_session.execute(select(SubscriptionRequest).where(SubscriptionRequest.id == old_id))
    ).scalar_one()
    assert old_row.status == SubscriptionStatus.SUPERSEDED.value
    assert old_row.response == "Welcome"
    assert old_row.response_by == 7000

    new_row = (
        await db_session.execute(select(SubscriptionRequest).where(SubscriptionRequest.id == new_id))
    ).scalar_one()
    assert new_row.status == SubscriptionStatus.APPROVED.value
    assert new_row.response == "Latest"
    assert await SubscriptionService(db_session).has_active_subscription(tg_user_id=uid) is True


@pytest.mark.asyncio
async def test_has_active_subscription_false_when_none_approved(db_session) -> None:
    uid = 99_002
    db_session.add(
        SubscriptionRequest(
            tg_user_id=uid,
            username="pending",
            full_name="Pending",
            status=SubscriptionStatus.PENDING.value,
        )
    )
    await db_session.commit()

    assert await SubscriptionService(db_session).has_active_subscription(tg_user_id=uid) is False


@pytest.mark.asyncio
async def test_stripe_agent_subscription_checkout_activates_agents_plan(db_session) -> None:
    uid = 99_020

    result = await GroupPaymentService(db_session)._handle_checkout_completed(
        {
            "id": "cs_test_agents_1",
            "metadata": {
                "payment_type": "agent_subscription",
                "tg_user_id": str(uid),
                "plan": "business",
                "duration_days": "30",
                "bot_kind": "agents",
            },
        }
    )

    assert result["status"] == "activated"

    row = (
        await db_session.execute(select(SubscriptionRequest).where(SubscriptionRequest.tg_user_id == uid))
    ).scalar_one()
    assert row.status == SubscriptionStatus.APPROVED.value
    assert row.plan == "business"
    assert row.bot_kind == "agents"
    assert row.expires_at is not None
