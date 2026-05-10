"""Join request approval tracking for protected groups."""

from __future__ import annotations
from typing import Optional

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from bot.db.base import Base


class JoinRequestApproval(Base):
    """Tracks pending join requests that require verification before approval."""

    __tablename__ = "join_request_approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    protected_group_tg_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    user_tg_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    invite_link: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    # Comma-separated list of required group TG IDs the user must join
    required_group_tg_ids: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Which required groups the user has joined (comma-separated TG IDs)
    verified_group_tg_ids: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    approved_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    decline_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
