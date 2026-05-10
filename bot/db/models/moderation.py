"""Moderation domain models."""

from __future__ import annotations
from typing import Optional

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from bot.db.base import Base


class ModerationLog(Base):
    __tablename__ = "moderation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, index=True)
    admin_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, index=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    details: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class Warning(Base):
    __tablename__ = "warnings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    issued_by: Mapped[Optional[int]] = mapped_column(BigInteger, index=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class ModerationSetting(Base):
    __tablename__ = "moderation_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    safe_mode: Mapped[bool] = mapped_column(Boolean, default=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    default_action: Mapped[str] = mapped_column(String(32), default="review")
    review_threshold: Mapped[float] = mapped_column(Float, default=0.65)
    auto_delete_threshold: Mapped[float] = mapped_column(Float, default=0.92)
    mute_threshold: Mapped[float] = mapped_column(Float, default=0.95)
    ban_threshold: Mapped[float] = mapped_column(Float, default=0.98)
    action_for_arabic_ads: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    action_for_investment_scam: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    action_for_crypto_scam: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    action_for_phishing_link: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    action_for_link_spam: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    action_for_repeated_promo: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    allowlisted_domains: Mapped[list[str]] = mapped_column(JSON, default=list)
    blocked_domains: Mapped[list[str]] = mapped_column(JSON, default=list)
    allowlisted_user_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    muted_duration_seconds: Mapped[int] = mapped_column(Integer, default=3600)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )


class ModerationEvent(Base):
    __tablename__ = "moderation_events"
    __table_args__ = (
        UniqueConstraint("group_id", "message_id", name="uq_moderation_events_group_message"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    text_preview: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(64))
    confidence: Mapped[float] = mapped_column(Float)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    matched_signals: Mapped[list[str]] = mapped_column(JSON, default=list)
    recommended_action: Mapped[str] = mapped_column(String(32))
    action_taken: Mapped[str] = mapped_column(String(32))
    dry_run: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(32))
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
