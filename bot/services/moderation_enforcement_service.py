from __future__ import annotations

from aiogram.types import ChatPermissions
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Group, ModerationLog, Warning
from bot.services.moderation_settings_store import ModerationSettingsStore


async def add_warning(
    session: AsyncSession,
    *,
    group_id: int,
    user_id: int,
    issued_by: int | None,
    reason: str | None,
    count: int = 1,
) -> Warning:
    warning = (
        await session.execute(
            select(Warning).where(
                Warning.group_id == group_id,
                Warning.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if warning is None:
        warning = Warning(
            group_id=group_id,
            user_id=user_id,
            issued_by=issued_by,
            reason=reason,
            count=max(count, 1),
        )
        session.add(warning)
        await session.flush()
        return warning

    warning.count += max(count, 1)
    warning.issued_by = issued_by
    if reason:
        warning.reason = reason
    await session.flush()
    return warning


async def maybe_mute_user(
    session: AsyncSession,
    *,
    group: Group,
    bot,
    user_id: int | None,
    admin_user_id: int | None,
    setting_key: str,
    threshold_key: str,
    log_action: str,
    reason: str | None,
    current_count: int,
    details: dict[str, object] | None = None,
) -> bool:
    if not user_id:
        return False
    moderation_settings = await ModerationSettingsStore(session).get_settings(group.id)
    enabled = getattr(moderation_settings, setting_key, False)
    if enabled is not True:
        return False
    limit = int(getattr(moderation_settings, threshold_key, 1))
    if current_count < limit:
        return False

    payload = dict(details or {})
    applied = True
    try:
        await bot.restrict_chat_member(
            group.tg_group_id,
            user_id,
            permissions=ChatPermissions(can_send_messages=False),
        )
    except Exception as exc:
        applied = False
        payload["error"] = str(exc)
    payload["telegram_applied"] = applied
    payload["setting_key"] = setting_key
    payload["threshold_key"] = threshold_key
    payload["count"] = current_count
    payload["limit"] = limit
    session.add(
        ModerationLog(
            group_id=group.id,
            action=log_action,
            target_user_id=user_id,
            admin_user_id=admin_user_id,
            reason=reason,
            details=payload,
        )
    )
    return applied


async def moderation_incident_count(
    session: AsyncSession,
    *,
    group_id: int,
    user_id: int,
    actions: tuple[str, ...],
) -> int:
    return int(
        (
            await session.execute(
                select(func.count(ModerationLog.id)).where(
                    ModerationLog.group_id == group_id,
                    ModerationLog.target_user_id == user_id,
                    ModerationLog.action.in_(actions),
                )
            )
        ).scalar_one()
        or 0
    )


async def maybe_remove_user_on_warning_limit(
    session: AsyncSession,
    *,
    group: Group,
    bot,
    user_id: int | None,
    admin_user_id: int | None,
    warning: Warning,
    reason: str | None,
    details: dict[str, object] | None = None,
) -> int | None:
    if not user_id:
        return None

    moderation_settings = await ModerationSettingsStore(session).get_settings(group.id)
    if moderation_settings.warn_auto_remove is not True:
        return None

    limit = moderation_settings.warn_remove_limit
    if warning.count < limit:
        return None

    payload = dict(details or {})
    payload["count"] = warning.count
    payload["limit"] = limit
    applied = True
    try:
        await bot.ban_chat_member(group.tg_group_id, user_id)
    except Exception as exc:
        applied = False
        payload["error"] = str(exc)
    payload["telegram_applied"] = applied
    session.add(
        ModerationLog(
            group_id=group.id,
            action="remove_warn_limit",
            target_user_id=user_id,
            admin_user_id=admin_user_id,
            reason=reason,
            details=payload,
        )
    )
    return limit


async def maybe_mute_user_on_warning_limit(
    session: AsyncSession,
    *,
    group: Group,
    bot,
    user_id: int | None,
    admin_user_id: int | None,
    warning: Warning,
    reason: str | None,
    details: dict[str, object] | None = None,
) -> int | None:
    if not user_id:
        return None

    moderation_settings = await ModerationSettingsStore(session).get_settings(group.id)
    if moderation_settings.warn_auto_mute is not True:
        return None

    limit = moderation_settings.warn_mute_limit
    if warning.count < limit:
        return None

    payload = dict(details or {})
    payload["count"] = warning.count
    payload["limit"] = limit
    applied = True
    try:
        await bot.restrict_chat_member(
            group.tg_group_id,
            user_id,
            permissions=ChatPermissions(can_send_messages=False),
        )
    except Exception as exc:
        applied = False
        payload["error"] = str(exc)
    payload["telegram_applied"] = applied
    session.add(
        ModerationLog(
            group_id=group.id,
            action="mute_warn_limit",
            target_user_id=user_id,
            admin_user_id=admin_user_id,
            reason=reason,
            details=payload,
        )
    )
    return limit
