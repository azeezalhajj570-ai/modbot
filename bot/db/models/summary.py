"""Daily admin summary domain models."""

from __future__ import annotations
from typing import Optional

from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from bot.db.base import Base


class GroupSummarySettings(Base):
    __tablename__ = "group_summary_settings"
    __table_args__ = (UniqueConstraint("group_id", name="uq_group_summary_settings_group_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    summary_time: Mapped[str] = mapped_column(String(5), default="21:00")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Aden")
    delivery_mode: Mapped[str] = mapped_column(String(32), default="dashboard_only")
    admin_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    include_top_users: Mapped[bool] = mapped_column(Boolean, default=True)
    include_links: Mapped[bool] = mapped_column(Boolean, default=True)
    include_moderation_events: Mapped[bool] = mapped_column(Boolean, default=True)
    include_unanswered_questions: Mapped[bool] = mapped_column(Boolean, default=True)
    include_recommendations: Mapped[bool] = mapped_column(Boolean, default=True)
    max_message_samples: Mapped[int] = mapped_column(Integer, default=500)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class DailyGroupSummary(Base):
    __tablename__ = "daily_group_summaries"
    __table_args__ = (
        UniqueConstraint("group_id", "summary_date", name="uq_daily_group_summary_group_date"),
        Index("ix_daily_group_summary_group_created", "group_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    summary_date: Mapped[date] = mapped_column(Date, index=True)
    total_messages: Mapped[int] = mapped_column(Integer, default=0)
    active_users_count: Mapped[int] = mapped_column(Integer, default=0)
    links_count: Mapped[int] = mapped_column(Integer, default=0)
    suspicious_messages_count: Mapped[int] = mapped_column(Integer, default=0)
    deleted_messages_count: Mapped[int] = mapped_column(Integer, default=0)
    top_users: Mapped[list] = mapped_column(JSON, default=list)
    top_topics: Mapped[list] = mapped_column(JSON, default=list)
    important_questions: Mapped[list] = mapped_column(JSON, default=list)
    unanswered_questions: Mapped[list] = mapped_column(JSON, default=list)
    links: Mapped[list] = mapped_column(JSON, default=list)
    moderation_highlights: Mapped[list] = mapped_column(JSON, default=list)
    recommendations: Mapped[list] = mapped_column(JSON, default=list)
    summary_text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="generated")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class GroupMessageActivity(Base):
    __tablename__ = "group_message_activity"
    __table_args__ = (
        UniqueConstraint("group_id", "message_id", name="uq_group_message_activity_group_message"),
        Index("ix_group_message_activity_group_created", "group_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    text_preview: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    normalized_text: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    has_link: Mapped[bool] = mapped_column(Boolean, default=False)
    link_domains: Mapped[list] = mapped_column(JSON, default=list)
    is_question: Mapped[bool] = mapped_column(Boolean, default=False)
    is_forwarded: Mapped[bool] = mapped_column(Boolean, default=False)
    reply_to_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)
