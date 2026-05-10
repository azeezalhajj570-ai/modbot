"""Group access and subscription management models."""

from __future__ import annotations
from typing import Optional

from datetime import datetime
from strenum import StrEnum

import sqlalchemy as sa
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from bot.db.base import Base


class GroupPaymentMode(StrEnum):
    MANUAL = "manual_payment"
    STRIPE = "stripe_checkout"
    STARS = "telegram_stars"


class GroupExpiryAction(StrEnum):
    REVIEW = "review"
    WARN = "warn"
    RESTRICT = "restrict"
    REMOVE = "remove"


class GroupSubscriberStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    REMOVED = "removed"


class GroupPaymentStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"
    CANCELLED = "cancelled"


class GroupSubscriptionSettings(Base):
    __tablename__ = "group_subscription_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    payment_mode: Mapped[str] = mapped_column(String(32), default=GroupPaymentMode.MANUAL)
    default_currency: Mapped[str] = mapped_column(String(8), default="USD")
    auto_approve_manual_payments: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_remove_expired: Mapped[bool] = mapped_column(Boolean, default=False)
    expiry_action: Mapped[str] = mapped_column(String(32), default=GroupExpiryAction.REVIEW)
    grace_period_days: Mapped[int] = mapped_column(Integer, default=3)
    reminder_days_before_expiry: Mapped[int] = mapped_column(Integer, default=2)
    invite_link_expire_seconds: Mapped[int] = mapped_column(Integer, default=86400)
    invite_link_member_limit: Mapped[int] = mapped_column(Integer, default=1)
    payment_instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )


class SubscriptionPlan(Base):
    __tablename__ = "group_subscription_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price_amount: Mapped[int] = mapped_column(Integer)  # In smallest currency unit (e.g., cents)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    duration_days: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    stripe_price_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )


class GroupSubscriber(Base):
    __tablename__ = "group_subscribers"
    __table_args__ = (
        Index(
            "uq_group_subscribers_active_one_per_user",
            "group_id",
            "user_id",
            unique=True,
            postgresql_where=sa.text("status IN ('active', 'pending')"),
            sqlite_where=sa.text("status IN ('active', 'pending')"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=GroupSubscriberStatus.PENDING, index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("group_subscription_plans.id", ondelete="SET NULL"), nullable=True)
    starts_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    payment_provider: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    payment_reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )


class PaymentRecord(Base):
    __tablename__ = "group_payment_records"
    __table_args__ = (
        UniqueConstraint("provider", "provider_reference", name="uq_payment_provider_ref"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    plan_id: Mapped[Optional[int]] = mapped_column(ForeignKey("group_subscription_plans.id", ondelete="SET NULL"), nullable=True)
    provider: Mapped[str] = mapped_column(String(32))
    amount: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(32), default=GroupPaymentStatus.PENDING, index=True)
    provider_reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )


class SubscriptionEvent(Base):
    __tablename__ = "group_subscription_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, index=True, nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    details_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
