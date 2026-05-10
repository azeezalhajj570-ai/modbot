from __future__ import annotations

import pytest
from datetime import datetime, timedelta
from sqlalchemy import select

from bot.db.models import PromotionCode, PromotionCodeRedemption, SubscriptionRequest, SubscriptionStatus
from bot.services.promotion_service import PromotionService, PromotionError


@pytest.mark.asyncio
async def test_redeem_valid_promo_creates_subscription(db_session) -> None:
    uid = 12345
    promo = PromotionCode(
        code="VALID10",
        duration_days=10,
        is_active=True,
    )
    db_session.add(promo)
    await db_session.commit()
    
    service = PromotionService(db_session)
    sub = await service.redeem_code(tg_user_id=uid, code="valid10")
    
    assert sub.status == SubscriptionStatus.APPROVED.value
    assert sub.expires_at is not None
    assert sub.promo_code_id == promo.id
    
    # Check used count
    await db_session.refresh(promo)
    assert promo.used_count == 1
    
    # Check redemption history
    stmt = select(PromotionCodeRedemption).where(PromotionCodeRedemption.tg_user_id == uid)
    redemption = (await db_session.execute(stmt)).scalar_one()
    assert redemption.promo_code_id == promo.id


@pytest.mark.asyncio
async def test_redeem_extends_existing_subscription(db_session) -> None:
    uid = 12345
    now = datetime.utcnow()
    future = now + timedelta(days=5)
    
    # Existing sub
    db_session.add(SubscriptionRequest(
        tg_user_id=uid,
        status=SubscriptionStatus.APPROVED.value,
        expires_at=future,
    ))
    
    promo = PromotionCode(
        code="EXTEND5",
        duration_days=5,
        is_active=True,
    )
    db_session.add(promo)
    await db_session.commit()
    
    service = PromotionService(db_session)
    sub = await service.redeem_code(tg_user_id=uid, code="EXTEND5")
    
    # Should be future + 5 days
    assert sub.expires_at.date() == (future + timedelta(days=5)).date()


@pytest.mark.asyncio
async def test_redeem_does_not_shorten_lifetime_subscription(db_session) -> None:
    uid = 12345
    db_session.add(SubscriptionRequest(
        tg_user_id=uid,
        status=SubscriptionStatus.APPROVED.value,
        expires_at=None,
    ))
    
    promo = PromotionCode(
        code="LIFETIME_TEST",
        duration_days=30,
        is_active=True,
    )
    db_session.add(promo)
    await db_session.commit()
    
    service = PromotionService(db_session)
    sub = await service.redeem_code(tg_user_id=uid, code="LIFETIME_TEST")
    
    assert sub.expires_at is None


@pytest.mark.asyncio
async def test_redeem_fails_for_inactive_promo(db_session) -> None:
    uid = 12345
    db_session.add(PromotionCode(
        code="INACTIVE",
        duration_days=10,
        is_active=False,
    ))
    await db_session.commit()
    
    service = PromotionService(db_session)
    with pytest.raises(PromotionError, match="no longer active"):
        await service.redeem_code(tg_user_id=uid, code="INACTIVE")


@pytest.mark.asyncio
async def test_redeem_fails_for_expired_promo(db_session) -> None:
    uid = 12345
    db_session.add(PromotionCode(
        code="EXPIRED",
        duration_days=10,
        expiry_date=datetime.utcnow() - timedelta(days=1),
    ))
    await db_session.commit()
    
    service = PromotionService(db_session)
    with pytest.raises(PromotionError, match="has expired"):
        await service.redeem_code(tg_user_id=uid, code="EXPIRED")


@pytest.mark.asyncio
async def test_redeem_fails_for_max_uses_reached(db_session) -> None:
    uid = 12345
    db_session.add(PromotionCode(
        code="MAXED",
        duration_days=10,
        max_uses=1,
        used_count=1,
    ))
    await db_session.commit()
    
    service = PromotionService(db_session)
    with pytest.raises(PromotionError, match="maximum usage limit"):
        await service.redeem_code(tg_user_id=uid, code="MAXED")


@pytest.mark.asyncio
async def test_redeem_fails_for_duplicate_redemption(db_session) -> None:
    uid = 12345
    promo = PromotionCode(
        code="ONCE",
        duration_days=10,
    )
    db_session.add(promo)
    await db_session.commit()
    
    service = PromotionService(db_session)
    first = await service.redeem_code(tg_user_id=uid, code="ONCE")
    second = await service.redeem_code(tg_user_id=uid, code="ONCE")
    
    # Idempotent — second call returns the same active subscription instead of error
    assert second.id == first.id
    assert second.status == 'approved'
