from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import DailyGroupSummary, Group, GroupAdminRole, GroupSummarySettings, User


logger = structlog.get_logger(__name__)


async def _admin_recipients(session: AsyncSession, group: Group, settings: GroupSummarySettings) -> list[int]:
    recipients: list[int] = []
    if settings.admin_chat_id is not None:
        recipients.append(int(settings.admin_chat_id))

    owner_tg_id = (
        await session.execute(
            select(User.tg_user_id)
            .join(Group, Group.owner_user_id == User.id)
            .where(Group.id == group.id)
        )
    ).scalar_one_or_none()
    if owner_tg_id is not None:
        recipients.append(int(owner_tg_id))

    admin_ids = (await session.execute(select(GroupAdminRole.user_id).where(GroupAdminRole.group_id == group.id))).scalars().all()
    recipients.extend(int(user_id) for user_id in admin_ids)

    unique: list[int] = []
    for recipient in recipients:
        if recipient not in unique:
            unique.append(recipient)
    return unique


async def send_daily_summary(
    session: AsyncSession,
    *,
    group: Group,
    summary: DailyGroupSummary,
    settings: GroupSummarySettings,
    bot,
) -> str:
    mode = settings.delivery_mode or "dashboard_only"
    if mode == "dashboard_only" or bot is None:
        return "generated"

    recipients: list[int] = []
    if mode == "admin_dm":
        recipients = await _admin_recipients(session, group, settings)
    elif mode == "group_message":
        recipients = [int(group.tg_group_id)]
    elif mode == "group_admin_thread":
        if settings.admin_chat_id is not None:
            recipients = [int(settings.admin_chat_id)]
        else:
            logger.warning("group_admin_thread mode requires admin_chat_id to be set", group_id=group.id)
    if not recipients:
        return "generated"

    for recipient in recipients:
        await bot.send_message(recipient, summary.summary_text)
    return "sent"
