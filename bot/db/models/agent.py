"""Agent domain models."""

from __future__ import annotations
from typing import Optional

from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.db.base import Base


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("linked_by_user_id", "external_account_id", name="uq_agent_linked_user_external_account"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, index=True, nullable=True)
    linked_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, index=True, nullable=True)
    group_id: Mapped[Optional[int]] = mapped_column(ForeignKey("groups.id", ondelete="SET NULL"), index=True, nullable=True)
    phone_number: Mapped[Optional[str]] = mapped_column(String(32), index=True, nullable=True)
    external_account_id: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    auth_state: Mapped[str] = mapped_column(String(32), default="active", index=True)
    session_string: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    phone_code_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    details: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    max_actions_per_hour: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_messages_per_day: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    min_delay_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cooldown_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    safety_mode_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    safety_mode_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    jobs: Mapped[list["AgentJob"]] = relationship(
        back_populates="agent",
        cascade="all, delete-orphan",
    )
    notifications: Mapped[list["AgentNotification"]] = relationship(
        back_populates="agent",
        cascade="all, delete-orphan",
    )
    leads: Mapped[list["AgentLead"]] = relationship(
        back_populates="agent",
        cascade="all, delete-orphan",
    )


class AgentJob(Base):
    __tablename__ = "agent_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    job_type: Mapped[str] = mapped_column(String(100), index=True)
    job_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    agent: Mapped[Agent] = relationship(back_populates="jobs")


class AgentNotification(Base):
    __tablename__ = "agent_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True, nullable=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(64), index=True, default="info")
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    is_seen: Mapped[bool] = mapped_column(default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    agent: Mapped[Optional[Agent]] = relationship(back_populates="notifications")


class AgentLead(Base):
    """Dedicated lead model for agent-captured leads with full CRM lifecycle."""

    __tablename__ = "agent_leads"
    __table_args__ = (
        UniqueConstraint("agent_id", "tg_user_id", "source_group_tg_id", name="uq_agent_lead_user_group"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    tg_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, index=True, nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_group_tg_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    source_group_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    message_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    lead_label: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="new")
    assigned_to: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    contact_info: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    last_contacted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    converted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    agent: Mapped[Agent] = relationship(back_populates="leads")
