from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.runtime.moderation import ModerationRuntimeService
from bot.db.models import Group, GroupAdminRole, GroupMember, ModerationLog, ScrapedGroup, User
from bot.db.session import get_session
from bot.services.admin_activity_service import AdminActivityService
from bot.services.admin_group_member_service import (
    AdminGroupMemberSearchConflictError,
    AdminGroupMemberSearchRateLimitedError,
    AdminGroupMemberSearchUnavailableError,
    AdminGroupMemberService,
)
from bot.services.admin_role_service import AdminRoleService
from bot.services.access_gate_service import AccessGateService
from bot.services.group_service import tg_group_id_candidates
from bot.services.moderation_settings_service import ModerationSettingsService
from bot.services.scraper_service import ScraperService
from bot.services.settings_service import SettingsService
from bot.services.telegram_webapp_auth import TelegramWebAppIdentity

from ..dependencies import ensure_group_admin, get_identity, require_bot_owner
from .auth_boundary import require_admin_boundary
from ._shared import (
    AccessGateUpdateRequest,
    MemberRoleUpdateRequest,
    ModerationActionRequest,
    ModerationSettingsUpdateRequest,
    NotificationFollowUpRequest,
    SettingsPatchRequest,
    WarningPatchRequest,
)

router = APIRouter(tags=["admin"], dependencies=[Depends(require_admin_boundary)])


@router.get("/api/admin/groups/{group_id}/moderation/ai-settings")
@router.get("/webapp/groups/{group_id}/moderation/ai-settings")
async def webapp_group_moderation_ai_settings(
    group_id: int,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_group_admin(group_id, session, identity)
    values = await ModerationSettingsService(session).get_settings(group_id)
    return {"group_id": group_id, "settings": values}


@router.patch("/api/admin/groups/{group_id}/moderation/ai-settings")
@router.patch("/webapp/groups/{group_id}/moderation/ai-settings")
async def webapp_patch_group_moderation_ai_settings(
    group_id: int,
    payload: ModerationSettingsUpdateRequest,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_group_admin(group_id, session, identity)
    values = await ModerationSettingsService(session).update_settings(
        group_id, payload.dict(exclude_unset=True)
    )
    return {"status": "ok", "group_id": group_id, "settings": values}


@router.get("/api/admin/groups/{group_id}/moderation/ai-events")
@router.get("/webapp/groups/{group_id}/moderation/ai-events")
async def webapp_group_moderation_ai_events(
    group_id: int,
    limit: int = Query(default=100, ge=1, le=200),
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    await ensure_group_admin(group_id, session, identity)
    return await ModerationSettingsService(session).list_events(group_id, limit=limit)


@router.get("/api/admin/groups/{group_id}/overview")
@router.get("/webapp/groups/{group_id}/overview")
async def webapp_group_overview(
    group_id: int,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
    id_type: str = Query(default="group", alias="id_type"),
) -> dict[str, Any]:
    if id_type == "scraped":
        scraped = (await session.execute(select(ScrapedGroup).where(ScrapedGroup.id == group_id))).scalar_one_or_none()
        if scraped is None:
            raise HTTPException(status_code=404, detail="Scraped group not found")
        admin_group = (await session.execute(select(Group).where(Group.tg_group_id.in_(tg_group_id_candidates(int(scraped.tg_group_id)))))).scalar_one_or_none()
        if admin_group is None:
            raise HTTPException(status_code=404, detail="No admin group found for this scraped group")
        group_id = admin_group.id
    await ensure_group_admin(group_id, session, identity)
    return await AdminActivityService(session).build_group_overview(group_id=group_id)


@router.get("/api/admin/groups/{group_id}/leads")
@router.get("/webapp/groups/{group_id}/leads")
async def webapp_group_leads(
    group_id: int,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    await ensure_group_admin(group_id, session, identity)
    return await AdminActivityService(session).list_leads(group_id=group_id)


@router.get("/api/admin/groups/{group_id}/notification-reports")
@router.get("/webapp/groups/{group_id}/notification-reports")
async def webapp_group_notification_reports(
    group_id: int,
    limit: int = Query(default=100, ge=1, le=200),
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    await ensure_group_admin(group_id, session, identity)
    return await AdminActivityService(session).list_notification_reports(group_id=group_id, limit=limit)


@router.post("/api/admin/groups/{group_id}/notification-reports/{log_id}/reply")
@router.post("/webapp/groups/{group_id}/notification-reports/{log_id}/reply")
async def webapp_reply_to_notification_report(
    group_id: int,
    log_id: int,
    payload: NotificationFollowUpRequest,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_group_admin(group_id, session, identity)
    return await AdminActivityService(session).reply_to_notification_report(
        group_id=group_id,
        log_id=log_id,
        actor_user_id=identity.user_id,
        text=payload.text,
    )


@router.get("/api/admin/groups/{group_id}/settings")
@router.get("/webapp/groups/{group_id}/settings")
async def webapp_group_settings(
    group_id: int,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_group_admin(group_id, session, identity)
    values = await SettingsService(session).get_all(group_id)
    return {"group_id": group_id, "settings": values}


@router.get("/api/admin/groups/{group_id}/access-gate")
@router.get("/webapp/groups/{group_id}/access-gate")
async def webapp_group_access_gate(
    group_id: int,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_group_admin(group_id, session, identity)
    required_tg_ids = await AccessGateService(session).list_required_group_tg_ids(group_id)
    candidate_rows = (
        await session.execute(
            select(Group.id, Group.title, Group.tg_group_id, GroupAdminRole.role)
            .join(GroupAdminRole, GroupAdminRole.group_id == Group.id)
            .where(GroupAdminRole.user_id == identity.user_id, Group.is_active.is_(True), Group.id != group_id)
            .order_by(Group.title.asc())
        )
    ).all()
    return {
        "group_id": group_id,
        "required_group_tg_ids": required_tg_ids,
        "candidates": [
            {"id": row.id, "title": row.title, "tg_group_id": row.tg_group_id, "role": row.role}
            for row in candidate_rows
        ],
    }


@router.patch("/api/admin/groups/{group_id}/access-gate")
@router.patch("/webapp/groups/{group_id}/access-gate")
async def webapp_update_group_access_gate(
    group_id: int,
    payload: AccessGateUpdateRequest,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_group_admin(group_id, session, identity)
    candidate_tg_ids = set(
        (
            await session.execute(
                select(Group.tg_group_id)
                .join(GroupAdminRole, GroupAdminRole.group_id == Group.id)
                .where(GroupAdminRole.user_id == identity.user_id, Group.is_active.is_(True), Group.id != group_id)
            )
        ).scalars()
    )
    requested: list[int] = []
    for value in payload.required_group_tg_ids:
        if value in candidate_tg_ids and value not in requested:
            requested.append(value)

    gate = AccessGateService(session)
    existing = set(await gate.list_required_group_tg_ids(group_id))
    requested_set = set(requested)
    for tg_id in existing - requested_set:
        await gate.remove_required_group(group_id, tg_id)
    for tg_id in requested:
        if tg_id not in existing:
            await gate.add_required_group(group_id, tg_id)
    return {"status": "ok", "group_id": group_id, "required_group_tg_ids": requested}


@router.patch("/api/admin/groups/{group_id}/settings")
@router.patch("/webapp/groups/{group_id}/settings")
async def webapp_patch_group_settings(
    group_id: int,
    payload: SettingsPatchRequest,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_group_admin(group_id, session, identity)
    service = SettingsService(session)

    changed: dict[str, bool | int | str] = {}
    for key, value in payload.settings.items():
        if not isinstance(key, str) or not key.strip():
            continue
        if isinstance(value, str) and len(value) > 2_000:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Setting {key} is too long")
        await service.set_value(group_id, key.strip(), value)
        changed[key.strip()] = value

    return {"status": "ok", "group_id": group_id, "changed": changed}


@router.get("/api/admin/groups/{group_id}/moderation/warnings")
@router.get("/webapp/groups/{group_id}/moderation/warnings")
async def webapp_group_warnings(
    group_id: int,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    await ensure_group_admin(group_id, session, identity)
    return await ModerationRuntimeService(session).list_warnings(group_id=group_id)


@router.post("/api/admin/groups/{group_id}/moderation/warnings")
@router.post("/webapp/groups/{group_id}/moderation/warnings")
async def webapp_add_warning(
    group_id: int,
    payload: WarningPatchRequest,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_group_admin(group_id, session, identity)
    return await ModerationRuntimeService(session).add_warning(
        group_id=group_id,
        actor_user_id=identity.user_id,
        user_id=payload.user_id,
        reason=payload.reason,
        count=payload.count,
    )


@router.delete("/api/admin/groups/{group_id}/moderation/warnings/{user_id}")
@router.delete("/webapp/groups/{group_id}/moderation/warnings/{user_id}")
async def webapp_clear_warning(
    group_id: int,
    user_id: int,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_group_admin(group_id, session, identity)
    return await ModerationRuntimeService(session).clear_warnings(
        group_id=group_id,
        actor_user_id=identity.user_id,
        user_id=user_id,
    )


@router.post("/api/admin/groups/{group_id}/moderation/actions")
@router.post("/webapp/groups/{group_id}/moderation/actions")
async def webapp_moderation_action(
    group_id: int,
    payload: ModerationActionRequest,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_group_admin(group_id, session, identity)
    return await ModerationRuntimeService(session).apply_action(
        group_id=group_id,
        actor_user_id=identity.user_id,
        user_id=payload.user_id,
        action=payload.action,
        reason=payload.reason,
        count=payload.count,
    )


@router.get("/api/admin/groups/{group_id}/moderation/restricted")
@router.get("/webapp/groups/{group_id}/moderation/restricted")
async def webapp_restricted_users(
    group_id: int,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    await ensure_group_admin(group_id, session, identity)
    from sqlalchemy import desc, func
    mute_actions = {"mute_user", "mute_warn_limit", "mute_ad_user", "mute_spam_user", "mute_unauthorized_command_user"}
    ban_actions = {"ban_user", "remove_warn_limit", "ban_unauthorized_command_user"}
    un_actions = {"unmute_user", "unban_user"}
    restricted_actions = mute_actions | ban_actions

    subq = (
        select(
            ModerationLog.target_user_id,
            ModerationLog.action,
            func.max(ModerationLog.created_at).label("max_created"),
        )
        .where(
            ModerationLog.group_id == group_id,
            ModerationLog.action.in_(restricted_actions | un_actions),
        )
        .group_by(ModerationLog.target_user_id, ModerationLog.action)
        .subquery()
    )

    latest_per_user = (
        select(
            ModerationLog.target_user_id,
            ModerationLog.action,
            ModerationLog.reason,
            ModerationLog.created_at,
            ModerationLog.details,
        )
        .where(
            ModerationLog.group_id == group_id,
            ModerationLog.action.in_(restricted_actions | un_actions),
        )
        .order_by(desc(ModerationLog.created_at))
    ).subquery()

    from sqlalchemy import and_
    rows = (
        await session.execute(
            select(
                latest_per_user.c.target_user_id,
                latest_per_user.c.action,
                latest_per_user.c.reason,
                latest_per_user.c.created_at,
                latest_per_user.c.details,
            )
            .distinct(latest_per_user.c.target_user_id)
            .order_by(latest_per_user.c.target_user_id, desc(latest_per_user.c.created_at))
        )
    ).all()

    restricted_users: dict[int, dict[str, Any]] = {}
    for row in rows:
        uid = int(row.target_user_id)
        if uid in restricted_users:
            continue
        if row.action in mute_actions:
            restricted_users[uid] = {"user_id": uid, "type": "mute", "reason": row.reason, "created_at": str(row.created_at), "details": row.details}
        elif row.action in ban_actions:
            restricted_users[uid] = {"user_id": uid, "type": "ban", "reason": row.reason, "created_at": str(row.created_at), "details": row.details}

    return list(restricted_users.values())


@router.get("/api/admin/groups/{group_id}/members")
@router.get("/webapp/groups/{group_id}/members")
async def webapp_members(
    group_id: int,
    q: str | None = Query(default=None, description="Search by username/full name"),
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    await ensure_group_admin(group_id, session, identity)
    group = (await session.execute(select(Group).where(Group.id == group_id))).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    normalized_query = str(q or "").strip().lower()
    stmt = (
        select(
            GroupMember.tg_user_id.label("user_id"),
            GroupMember.username.label("member_username"),
            GroupMember.full_name.label("member_full_name"),
            GroupMember.role.label("member_role"),
            GroupMember.created_at.label("member_created_at"),
            GroupAdminRole.role.label("admin_role"),
            GroupAdminRole.created_at.label("role_created_at"),
            User.username.label("user_username"),
            User.full_name.label("user_full_name"),
        )
        .select_from(GroupMember)
        .join(User, User.tg_user_id == GroupMember.tg_user_id, isouter=True)
        .join(
            GroupAdminRole,
            (GroupAdminRole.group_id == GroupMember.group_id) & (GroupAdminRole.user_id == GroupMember.tg_user_id),
            isouter=True,
        )
        .where(GroupMember.group_id == group_id)
        .order_by(GroupMember.full_name.asc(), GroupMember.username.asc(), GroupMember.tg_user_id.asc())
    )
    rows = (await session.execute(stmt)).all()
    scraped_by_user_id = await ScraperService(session).get_scraped_member_activity(
        tg_group_id=int(group.tg_group_id),
        user_ids=[int(row.user_id) for row in rows if row.user_id is not None],
    )
    result = []
    for row in rows:
        username = row.member_username or row.user_username or ""
        full_name = row.member_full_name or row.user_full_name or ""
        if normalized_query and normalized_query not in username.lower() and normalized_query not in full_name.lower():
            continue
        created_at = row.member_created_at or row.role_created_at
        scraped_payload = scraped_by_user_id.get(int(row.user_id), {})
        result.append(
            {
                "user_id": row.user_id,
                "role": row.admin_role or row.member_role or "member",
                "username": username or None,
                "full_name": full_name or None,
                "created_at": created_at.isoformat() if created_at is not None else None,
                "scraped_message_count": int(scraped_payload.get("scraped_message_count") or 0),
                "scraped_messages_preview": list(scraped_payload.get("scraped_messages_preview") or []),
            }
        )
    return result


@router.get("/api/admin/groups/{group_id}/member-search")
@router.get("/webapp/groups/{group_id}/member-search")
async def webapp_group_member_search(
    group_id: int,
    q: str | None = Query(default=None, description="Search by username/full name"),
    limit: int = Query(default=25, ge=1, le=50),
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    await ensure_group_admin(group_id, session, identity)
    try:
        return await AdminGroupMemberService(session).search_group_members(
            actor_user_id=identity.user_id,
            group_id=group_id,
            query=q,
            limit=limit,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except AdminGroupMemberSearchRateLimitedError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc
    except AdminGroupMemberSearchConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except AdminGroupMemberSearchUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/api/admin/groups/{group_id}/members/{user_id}/role")
@router.post("/webapp/groups/{group_id}/members/{user_id}/role")
async def webapp_set_member_role(
    group_id: int,
    user_id: int,
    payload: MemberRoleUpdateRequest | None = None,
    role: str | None = Query(default=None, pattern="^(owner|super_admin|admin|moderator)$"),
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_group_admin(group_id, session, identity)
    resolved_role = payload.role if payload is not None else role
    if resolved_role is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Missing role")
    return await AdminRoleService(session).set_member_role(
        group_id=group_id,
        actor_user_id=identity.user_id,
        user_id=user_id,
        role=resolved_role,
    )


@router.get("/api/admin/groups/{group_id}/logs")
@router.get("/webapp/groups/{group_id}/logs")
async def webapp_logs(
    group_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    await ensure_group_admin(group_id, session, identity)
    return await AdminActivityService(session).list_logs(group_id=group_id, limit=limit)


@router.get("/api/admin/groups/{group_id}/notifications")
@router.get("/webapp/groups/{group_id}/notifications")
async def webapp_group_notifications(
    group_id: int,
    limit: int = Query(default=50, ge=1, le=100),
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_group_admin(group_id, session, identity)
    from bot.agents.agent_notification_service import AgentNotificationService
    return await AgentNotificationService(session).list_notifications(
        actor_user_id=identity.user_id,
        group_id=group_id,
        limit=limit,
    )


@router.post("/api/admin/groups/{group_id}/notifications/mark-seen")
@router.post("/webapp/groups/{group_id}/notifications/mark-seen")
async def webapp_mark_group_notifications_seen(
    group_id: int,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_group_admin(group_id, session, identity)
    from bot.agents.agent_notification_service import AgentNotificationService
    updated = await AgentNotificationService(session).mark_all_seen(
        actor_user_id=identity.user_id,
        group_id=group_id,
    )
    return {"status": "ok", "updated": updated}


# ─── Subscription management (owner only) ────────────────────────────────────

@router.get("/api/admin/subscriptions")
@router.get("/webapp/subscriptions")
async def webapp_list_subscriptions(
    bot_kind: str | None = Query(default=None),
    _identity: TelegramWebAppIdentity = Depends(require_bot_owner),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    from bot.services.subscription_service import SubscriptionService
    subs = await SubscriptionService(session).list_active_subscriptions(bot_kind=bot_kind)
    return [
        {
            "tg_user_id": s.tg_user_id,
            "username": s.username,
            "full_name": s.full_name,
            "plan": s.plan,
            "status": s.status,
            "bot_kind": s.bot_kind,
            "expires_at": s.expires_at.isoformat() if s.expires_at else None,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in subs
    ]


@router.put("/api/admin/subscriptions/{tg_user_id}")
@router.put("/webapp/subscriptions/{tg_user_id}")
async def webapp_set_user_plan(
    tg_user_id: int,
    payload: dict[str, Any],
    identity: TelegramWebAppIdentity = Depends(require_bot_owner),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    plan = str(payload.get("plan", "free")).strip().lower()
    if plan not in ("free", "pro", "business"):
        raise HTTPException(status_code=422, detail="plan must be free, pro, or business")
    bot_kind = str(payload.get("bot_kind") or "").strip() or None

    from bot.services.subscription_service import SubscriptionService
    from bot.services.user_service import UserService
    user = await UserService(session).get_by_tg_id(tg_user_id=tg_user_id)
    sub = await SubscriptionService(session).set_user_plan(
        tg_user_id=tg_user_id,
        plan=plan,
        username=user.username if user else None,
        full_name=user.full_name if user else None,
        language_code=user.language_code if user else None,
        expires_at=None,
        responder_id=identity.user_id,
        bot_kind=bot_kind,
    )
    return {
        "tg_user_id": sub.tg_user_id,
        "username": sub.username,
        "full_name": sub.full_name,
        "plan": sub.plan,
        "status": sub.status,
        "bot_kind": sub.bot_kind,
        "expires_at": sub.expires_at.isoformat() if sub.expires_at else None,
    }


@router.delete("/api/admin/subscriptions/{tg_user_id}")
@router.delete("/webapp/subscriptions/{tg_user_id}")
async def webapp_cancel_subscription(
    tg_user_id: int,
    bot_kind: str | None = Query(default=None),
    identity: TelegramWebAppIdentity = Depends(require_bot_owner),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    from bot.services.subscription_service import SubscriptionService
    cancelled = await SubscriptionService(session).cancel_subscription(
        tg_user_id=tg_user_id,
        responder_id=identity.user_id,
        bot_kind=bot_kind,
    )
    if not cancelled:
        raise HTTPException(status_code=404, detail="No active subscription found for this user")
    return {"status": "ok", "message": "Subscription cancelled"}


__all__ = ["router"]
