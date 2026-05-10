"""Scraper domain models for groups/channels messages and members."""

from __future__ import annotations
from typing import Optional

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from bot.db.base import Base


class ScrapedGroup(Base):
    """Metadata about scraped Telegram groups/channels."""

    __tablename__ = "scraped_groups"
    __table_args__ = (
        Index("ix_scraped_groups_type", "group_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_group_id: Mapped[int] = mapped_column(BigInteger, index=True, unique=True)
    last_agent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    group_type: Mapped[str] = mapped_column(String(32), default="group", index=True)  # group, channel, supergroup
    member_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_data: Mapped[dict] = mapped_column(JSON, default=dict)
    scrape_state: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class ScrapedMessage(Base):
    """Scraped messages from groups/channels."""

    __tablename__ = "scraped_messages"
    __table_args__ = (
        Index("ix_scraped_messages_tg_group_id", "tg_group_id"),
        Index("ix_scraped_messages_message_id", "tg_group_id", "message_id", unique=True),
        Index("ix_scraped_messages_sender_id", "sender_user_id"),
        Index("ix_scraped_messages_date", "message_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scraped_group_id: Mapped[int] = mapped_column(ForeignKey("scraped_groups.id", ondelete="CASCADE"), index=True)
    tg_group_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int] = mapped_column(BigInteger)
    sender_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    sender_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sender_first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sender_last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    message_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    message_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    message_type: Mapped[str] = mapped_column(String(32), default="text", index=True)  # text, photo, video, document, etc.
    media_file_id: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    media_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    reply_to_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    reply_to_top_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    forward_from_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    raw_data: Mapped[dict] = mapped_column(JSON, default=dict)
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class ScrapedMember(Base):
    """Scraped members from groups/channels."""

    __tablename__ = "scraped_members"
    __table_args__ = (
        Index("ix_scraped_members_tg_group_id", "tg_group_id"),
        Index("ix_scraped_members_user_id", "tg_user_id"),
        Index("ix_scraped_members_group_user", "tg_group_id", "tg_user_id", unique=True),
        Index("ix_scraped_members_username", "username"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scraped_group_id: Mapped[int] = mapped_column(ForeignKey("scraped_groups.id", ondelete="CASCADE"), index=True)
    tg_group_id: Mapped[int] = mapped_column(BigInteger)
    tg_user_id: Mapped[int] = mapped_column(BigInteger)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False)
    role: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # creator, admin, member, restricted
    joined_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_data: Mapped[dict] = mapped_column(JSON, default=dict)
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class ScrapedConversation(Base):
    """Conversations built from scraped messages."""

    __tablename__ = "scraped_conversations"
    __table_args__ = (
        Index("ix_scraped_conv_group_id", "scraped_group_id"),
        Index("ix_scraped_conv_last_message", "last_message_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scraped_group_id: Mapped[int] = mapped_column(ForeignKey("scraped_groups.id", ondelete="CASCADE"), index=True)
    tg_group_id: Mapped[int] = mapped_column(BigInteger)
    root_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    root_message_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    root_sender_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    root_sender_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    participant_count: Mapped[int] = mapped_column(Integer, default=0)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    first_message_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_message_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    is_topic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class ScrapedDailySummary(Base):
    """AI-generated daily summaries from scraped messages (archive-tier storage)."""

    __tablename__ = "scraped_daily_summaries"
    __table_args__ = (
        Index("ix_daily_summaries_group_date", "scraped_group_id", "date", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scraped_group_id: Mapped[int] = mapped_column(ForeignKey("scraped_groups.id", ondelete="CASCADE"), index=True)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    active_users: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    top_topics: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class GroupKnowledge(Base):
    """Structured knowledge extracted from group messages via AI analysis."""

    __tablename__ = "group_knowledge"
    __table_args__ = (
        Index("ix_group_knowledge_type", "knowledge_type"),
        Index("ix_group_knowledge_group", "scraped_group_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scraped_group_id: Mapped[int] = mapped_column(ForeignKey("scraped_groups.id", ondelete="CASCADE"), index=True)
    knowledge_type: Mapped[str] = mapped_column(String(32), index=True)  # faq, topic, entity, decision, trend, consensus
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_message_ids: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float] = mapped_column(default=0.5)
    metadata_json: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)
    first_seen: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_updated: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class ScrapedLead(Base):
    """Potential leads extracted from group messages (contact intent, buying signals)."""

    __tablename__ = "scraped_leads"
    __table_args__ = (
        Index("ix_scraped_leads_group_id", "scraped_group_id"),
        Index("ix_scraped_leads_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scraped_group_id: Mapped[int] = mapped_column(ForeignKey("scraped_groups.id", ondelete="CASCADE"), index=True)
    source_message_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    sender_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    sender_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    signal: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # buying_intent, contact_request, support_need, hiring, partnership
    excerpt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    contact_info: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="new")  # new, contacted, converted, dismissed
    confidence: Mapped[float] = mapped_column(default=0.5)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
