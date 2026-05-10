"""Service for recording owner-level audit log entries."""

from __future__ import annotations
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import OwnerAuditLog


logger = structlog.get_logger(__name__)


async def log_owner_action(
    db: AsyncSession,
    actor_id: int,
    action: str,
    target_type: str,
    target_id: str | int,
    detail: dict | None = None,
) -> None:
    entry = OwnerAuditLog(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        detail=detail,
    )
    db.add(entry)
    await db.commit()
    logger.info("owner_action_logged", actor_id=actor_id, action=action, target_id=str(target_id))
