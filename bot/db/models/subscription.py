"""Subscription and promotion domain models."""

from __future__ import annotations
from typing import Optional

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from bot.db.base import Base


class SubscriptionRequest(Base):
    __tablename__ = "subscription_requests"
    __table_args__ = (
        Index(
            "uq_subscription_requests_one_approved_per_tg_user",
            "tg_user_id",
            unique=True,
            postgresql_where=sa.text("status = 'approved'"),
            sqlite_where=sa.text("status = 'approved'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    language_code: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True, default="pending")
    response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    response_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    plan: Mapped[str] = mapped_column(String(32), default="pro", index=True)
    bot_kind: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)  # admin, agents, or null (any)
    promo_code_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("promotion_codes.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class PromotionCode(Base):
    __tablename__ = "promotion_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    plan: Mapped[str] = mapped_column(String(32), default="pro")
    duration_days: Mapped[int] = mapped_column(Integer)
    max_uses: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(default=True)
    bot_kind: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)  # admin, agents, or null (any)
    expiry_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class PromotionCodeRedemption(Base):
    __tablename__ = "promotion_code_redemptions"
    __table_args__ = (
        UniqueConstraint("promo_code_id", "tg_user_id", name="uq_promo_code_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    promo_code_id: Mapped[int] = mapped_column(ForeignKey("promotion_codes.id", ondelete="CASCADE"))
    tg_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    subscription_request_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("subscription_requests.id", ondelete="SET NULL"),
        nullable=True,
    )
    redeemed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
