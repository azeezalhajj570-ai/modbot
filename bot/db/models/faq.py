"""FAQ-related database models."""

from __future__ import annotations

from datetime import datetime
from strenum import StrEnum
from typing import Optional, TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.db.base import Base

if TYPE_CHECKING:
    from bot.db.models.group import Group
    from bot.db.models.user import User


class FAQMode(StrEnum):
    DISABLED = "disabled"
    ADMIN_SUGGESTION = "admin_suggestion"
    AUTO_REPLY = "auto_reply"


class FAQSourceType(StrEnum):
    MANUAL = "manual"
    PINNED_MESSAGE = "pinned_message"
    DOCUMENT = "document"
    URL = "url"
    IMPORTED = "imported"


class FAQInteractionStatus(StrEnum):
    SENT = "sent"
    SUGGESTED = "suggested"
    UNANSWERED = "unanswered"
    SKIPPED = "skipped"
    ERROR = "error"


class UnansweredQuestionStatus(StrEnum):
    NEW = "new"
    REVIEWED = "reviewed"
    CONVERTED_TO_FAQ = "converted_to_faq"
    IGNORED = "ignored"


class FAQSettings(Base):
    __tablename__ = "faq_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    safe_mode: Mapped[bool] = mapped_column(Boolean, default=True)
    default_mode: Mapped[FAQMode] = mapped_column(String(32), default=FAQMode.ADMIN_SUGGESTION.value)
    auto_reply_threshold: Mapped[float] = mapped_column(Float, default=0.85)
    suggestion_threshold: Mapped[float] = mapped_column(Float, default=0.60)
    max_replies_per_user_per_hour: Mapped[int] = mapped_column(Integer, default=3)
    max_replies_per_group_per_hour: Mapped[int] = mapped_column(Integer, default=20)
    answer_cooldown_seconds: Mapped[int] = mapped_column(Integer, default=60)
    log_unanswered_questions: Mapped[bool] = mapped_column(Boolean, default=True)
    require_admin_approved_sources: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow
    )

    group: Mapped[Group] = relationship("Group")


class FAQEntry(Base):
    __tablename__ = "faq_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    source_type: Mapped[FAQSourceType] = mapped_column(String(32), default=FAQSourceType.MANUAL.value)
    source_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    approved_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow
    )

    group: Mapped[Group] = relationship("Group")
    approved_by: Mapped[Optional[User]] = relationship("User", foreign_keys=[approved_by_user_id])
    created_by: Mapped[Optional[User]] = relationship("User", foreign_keys=[created_by_user_id])


class FAQInteraction(Base):
    __tablename__ = "faq_interactions"
    __table_args__ = (UniqueConstraint("group_id", "message_id", name="uq_faq_interaction_group_message"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(BigInteger)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    user_question_preview: Mapped[str] = mapped_column(Text)
    matched_faq_entry_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("faq_entries.id", ondelete="SET NULL"), 
        nullable=True
    )
    confidence: Mapped[float] = mapped_column(Float)
    mode: Mapped[str] = mapped_column(String(32))  # auto_reply, admin_suggestion, unanswered, skipped
    answer_preview: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[FAQInteractionStatus] = mapped_column(String(32))
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow
    )

    group: Mapped[Group] = relationship("Group")
    matched_faq_entry: Mapped[Optional[FAQEntry]] = relationship("FAQEntry")


class UnansweredQuestion(Base):
    __tablename__ = "unanswered_questions"
    __table_args__ = (UniqueConstraint("group_id", "normalized_question_hash", name="uq_unanswered_question_group_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(BigInteger)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    question_preview: Mapped[str] = mapped_column(Text)
    normalized_question: Mapped[str] = mapped_column(Text)
    normalized_question_hash: Mapped[str] = mapped_column(String(64))
    frequency_count: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[UnansweredQuestionStatus] = mapped_column(
        String(32), 
        default=UnansweredQuestionStatus.NEW.value
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    group: Mapped[Group] = relationship("Group")
