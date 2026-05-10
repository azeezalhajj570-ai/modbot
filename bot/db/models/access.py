"""Access-control domain models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from bot.db.base import Base


class GroupAccessRequirement(Base):
    __tablename__ = "group_access_requirements"
    __table_args__ = (
        UniqueConstraint("protected_group_id", "required_group_tg_id", name="uq_group_access_requirement"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    protected_group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    required_group_tg_id: Mapped[int] = mapped_column(BigInteger, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class PrivateAccessRequirement(Base):
    __tablename__ = "private_access_requirements"
    __table_args__ = (
        UniqueConstraint("required_group_tg_id", name="uq_private_access_requirement"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    required_group_tg_id: Mapped[int] = mapped_column(BigInteger, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
