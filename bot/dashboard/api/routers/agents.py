from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from bot.agents.account_group_membership_service import AccountGroupMembershipService
from bot.agents.agent_notification_service import AgentNotificationService
from bot.agents.account_session_service import AccountSessionService
from bot.agents.agent_job_service import AgentJobService
from bot.agents.linked_account_service import LinkedAccountService
from bot.agents.dispatch import dispatch_agent_job
from bot.db.session import get_session
from bot.services.scraper_service import ScraperService
from bot.services.telegram_webapp_auth import TelegramWebAppIdentity

from ..dependencies import ensure_agent_admin, ensure_group_admin, get_identity, require_active_subscription, require_business_plan
from .auth_boundary import require_agents_boundary, require_any_boundary
from ._shared import (
    AgentJobCreateRequest,
    AgentLinkRequest,
    AgentLoginCodeRequest,
    AgentLoginPasswordRequest,
    AgentLoginStartRequest,
    AgentSafetyUpdateRequest,
    AgentUpdateRequest,
    LeadUpdateRequest,
    serialize_agent,
)

router = APIRouter(tags=["agents"])


@router.get("/api/agents", dependencies=[Depends(require_any_boundary(["admin", "agents"]))])
@router.get("/webapp/agents/list", dependencies=[Depends(require_any_boundary(["admin", "agents"]))])
async def webapp_agents(
    group_id: int | None = Query(default=None, ge=1),
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    agents = await LinkedAccountService(session).list_agents(actor_user_id=identity.user_id, group_id=group_id)
    return [serialize_agent(agent) for agent in agents]


@router.post("/api/agents/link", dependencies=[Depends(require_agents_boundary)])
@router.post("/webapp/agents/link", dependencies=[Depends(require_agents_boundary)])
async def webapp_link_agent(
    payload: AgentLinkRequest,
    identity: TelegramWebAppIdentity = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    # Check plan limits
    from bot.config import get_settings
    from bot.services.subscription_service import SubscriptionService
    
    is_owner = identity.user_id in get_settings().bot_owner_ids
    if not is_owner:
        sub = await SubscriptionService(session).get_active_subscription(tg_user_id=identity.user_id)
        if sub and sub.plan == "pro":
            existing = await LinkedAccountService(session).list_agents(actor_user_id=identity.user_id)
            if len(existing) >= 1:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Pro plan is limited to 1 linked account. Upgrade to Business for more."
                )

    try:
        agent = await LinkedAccountService(session).create_agent(
            actor_user_id=identity.user_id,
            group_id=payload.group_id,
            external_account_id=(payload.name or payload.external_account_id),
            phone_number=payload.phone_number,
            telegram_user_id=payload.telegram_user_id,
            metadata={
                **payload.metadata,
                **({"display_name": payload.name.strip()} if payload.name and payload.name.strip() else {}),
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return {"status": "ok", "agent": serialize_agent(agent)}


@router.post("/api/agents/auth/start", dependencies=[Depends(require_agents_boundary)])
@router.post("/webapp/agents/auth/start", dependencies=[Depends(require_agents_boundary)])
async def webapp_start_agent_auth(
    payload: AgentLoginStartRequest,
    identity: TelegramWebAppIdentity = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        agent = await AccountSessionService(session).start_agent_login(
            actor_user_id=identity.user_id,
            group_id=payload.group_id,
            phone_number=payload.phone_number,
            agent_id=payload.agent_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return {"status": "ok", "agent": serialize_agent(agent)}


@router.post("/api/agents/{agent_id}/auth/code", dependencies=[Depends(require_agents_boundary)])
@router.post("/webapp/agents/{agent_id}/auth/code", dependencies=[Depends(require_agents_boundary)])
async def webapp_complete_agent_auth_code(
    agent_id: int,
    payload: AgentLoginCodeRequest,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    agent = await ensure_agent_admin(agent_id, session, identity)
    try:
        updated = await AccountSessionService(session).complete_agent_code(
            actor_user_id=identity.user_id,
            agent_id=agent.id,
            code=payload.code,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return {"status": "ok", "agent": serialize_agent(updated)}


@router.post("/api/agents/{agent_id}/auth/password", dependencies=[Depends(require_agents_boundary)])
@router.post("/webapp/agents/{agent_id}/auth/password", dependencies=[Depends(require_agents_boundary)])
async def webapp_complete_agent_auth_password(
    agent_id: int,
    payload: AgentLoginPasswordRequest,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    agent = await ensure_agent_admin(agent_id, session, identity)
    try:
        updated = await AccountSessionService(session).complete_agent_password(
            actor_user_id=identity.user_id,
            agent_id=agent.id,
            password=payload.password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return {"status": "ok", "agent": serialize_agent(updated)}


@router.get("/api/agents/{agent_id}/jobs", dependencies=[Depends(require_agents_boundary)])
@router.get("/webapp/agents/{agent_id}/jobs", dependencies=[Depends(require_agents_boundary)])
async def webapp_agent_jobs(
    agent_id: int,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    agent = await ensure_agent_admin(agent_id, session, identity)
    rows = await AgentJobService(session).list_agent_jobs(actor_user_id=identity.user_id, agent_id=agent.id)
    return [
        {
            "id": job.id,
            "agent_id": job.agent_id,
            "job_type": job.job_type,
            "job_payload": job.job_payload,
            "status": job.status,
        }
        for job in rows
    ]


@router.get("/api/agents/{agent_id}/notifications", dependencies=[Depends(require_agents_boundary)])
@router.get("/webapp/agents/{agent_id}/notifications", dependencies=[Depends(require_agents_boundary)])
async def webapp_agent_notifications(
    agent_id: int,
    limit: int = Query(default=50, ge=1, le=100),
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    agent = await ensure_agent_admin(agent_id, session, identity)
    return await AgentNotificationService(session).list_notifications(
        actor_user_id=identity.user_id,
        agent_id=agent.id,
        limit=limit,
    )


@router.post("/api/agents/{agent_id}/notifications/mark-seen", dependencies=[Depends(require_agents_boundary)])
@router.post("/webapp/agents/{agent_id}/notifications/mark-seen", dependencies=[Depends(require_agents_boundary)])
async def webapp_mark_agent_notifications_seen(
    agent_id: int,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    agent = await ensure_agent_admin(agent_id, session, identity)
    updated = await AgentNotificationService(session).mark_all_seen(
        actor_user_id=identity.user_id,
        agent_id=agent.id,
    )
    return {"status": "ok", "updated": updated}


@router.post("/api/agents/{agent_id}/sync-workspace", dependencies=[Depends(require_agents_boundary)])
@router.post("/webapp/agents/{agent_id}/sync-workspace", dependencies=[Depends(require_agents_boundary)])
async def webapp_sync_workspace(
    agent_id: int,
    identity: TelegramWebAppIdentity = Depends(require_business_plan),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    agent = await ensure_agent_admin(agent_id, session, identity)
    synced = await ScraperService(session).sync_agent_groups(agent_id=agent.id)
    return {"status": "ok", "count": len(synced)}


@router.get("/api/agents/{agent_id}/groups", dependencies=[Depends(require_any_boundary(["admin", "agents"]))])
@router.get("/webapp/agents/{agent_id}/groups", dependencies=[Depends(require_any_boundary(["admin", "agents"]))])
async def webapp_agent_groups(
    agent_id: int,
    q: str | None = Query(default=None),
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    agent = await ensure_agent_admin(agent_id, session, identity)
    return await AccountGroupMembershipService(session).list_managed_member_groups(
        actor_user_id=identity.user_id,
        agent_id=agent.id,
        query=q,
    )


@router.get("/api/agents/{agent_id}/member-search", dependencies=[Depends(require_agents_boundary)])
@router.get("/webapp/agents/{agent_id}/member-search", dependencies=[Depends(require_agents_boundary)])
async def webapp_agent_member_search(
    agent_id: int,
    tg_group_id: int = Query(...),
    q: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=50),
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    agent = await ensure_agent_admin(agent_id, session, identity)
    try:
        payload = await AccountGroupMembershipService(session).list_scraped_agent_group_members(
            actor_user_id=identity.user_id,
            agent_id=agent.id,
            tg_group_id=tg_group_id,
            query=q,
            page=1,
            page_size=limit,
        )
        return payload["members"]
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/api/agents/{agent_id}/groups/{tg_group_id}/members", dependencies=[Depends(require_agents_boundary)])
@router.get("/webapp/agents/{agent_id}/groups/{tg_group_id}/members", dependencies=[Depends(require_agents_boundary)])
async def webapp_agent_group_members(
    agent_id: int,
    tg_group_id: int,
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=50),
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    agent = await ensure_agent_admin(agent_id, session, identity)
    try:
        return await AccountGroupMembershipService(session).list_scraped_agent_group_members(
            actor_user_id=identity.user_id,
            agent_id=agent.id,
            tg_group_id=tg_group_id,
            query=q,
            page=page,
            page_size=page_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/api/agents/{agent_id}/groups/{tg_group_id}/members/{user_id}/messages", dependencies=[Depends(require_agents_boundary)])
@router.get("/webapp/agents/{agent_id}/groups/{tg_group_id}/members/{user_id}/messages", dependencies=[Depends(require_agents_boundary)])
async def webapp_agent_group_member_messages(
    agent_id: int,
    tg_group_id: int,
    user_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    agent = await ensure_agent_admin(agent_id, session, identity)
    try:
        return await AccountGroupMembershipService(session).list_scraped_agent_group_member_messages(
            actor_user_id=identity.user_id,
            agent_id=agent.id,
            tg_group_id=tg_group_id,
            user_id=user_id,
            page=page,
            page_size=page_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/api/agents/{agent_id}/groups/{tg_group_id}/scrape-members", dependencies=[Depends(require_agents_boundary)])
@router.post("/webapp/agents/{agent_id}/groups/{tg_group_id}/scrape-members", dependencies=[Depends(require_agents_boundary)])
async def webapp_agent_group_scrape_members(
    agent_id: int,
    tg_group_id: int,
    limit: int = Query(default=500, ge=1, le=50000),
    message_limit: int | None = Query(default=None, ge=1, le=50000),
    max_age_days: int | None = Query(default=None, ge=1, le=3650),
    identity: TelegramWebAppIdentity = Depends(require_business_plan),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    agent = await ensure_agent_admin(agent_id, session, identity)
    try:
        return await AccountGroupMembershipService(session).scrape_agent_member_group(
            actor_user_id=identity.user_id,
            agent_id=agent.id,
            tg_group_id=tg_group_id,
            limit=limit,
            message_limit=message_limit,
            max_age_days=max_age_days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.patch("/api/agents/{agent_id}", dependencies=[Depends(require_agents_boundary)])
@router.patch("/webapp/agents/{agent_id}", dependencies=[Depends(require_agents_boundary)])
async def webapp_update_agent(
    agent_id: int,
    payload: AgentUpdateRequest,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    agent = await ensure_agent_admin(agent_id, session, identity)
    try:
        updated = await LinkedAccountService(session).update_agent(
            actor_user_id=identity.user_id,
            agent_id=agent.id,
            external_account_id=(payload.name or payload.external_account_id),
            phone_number=payload.phone_number,
            telegram_user_id=payload.telegram_user_id,
            metadata={
                **payload.metadata,
                **({"display_name": payload.name.strip()} if payload.name and payload.name.strip() else {}),
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return {"status": "ok", "agent": serialize_agent(updated)}


@router.post("/api/agents/{agent_id}/jobs", dependencies=[Depends(require_agents_boundary)])
@router.post("/webapp/agents/{agent_id}/jobs", dependencies=[Depends(require_agents_boundary)])
async def webapp_create_agent_job(
    agent_id: int,
    payload: AgentJobCreateRequest,
    identity: TelegramWebAppIdentity = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    agent = await ensure_agent_admin(agent_id, session, identity)
    
    # Restrict scraping jobs to business plan
    if payload.job_type in {"scraper_full_group", "sync_workspace"}:
        from bot.config import get_settings
        from bot.services.subscription_service import SubscriptionService
        is_owner = identity.user_id in get_settings().bot_owner_ids
        if not is_owner:
            sub = await SubscriptionService(session).get_active_subscription(tg_user_id=identity.user_id)
            if not sub or sub.plan != "business":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Business plan required for scraping features"
                )

    try:
        job = await AgentJobService(session).create_job(
            actor_user_id=identity.user_id,
            agent_id=agent.id,
            job_type=payload.job_type,
            job_payload=payload.job_payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    await dispatch_agent_job(job.id)
    return {"status": "ok", "job": {"id": job.id, "agent_id": job.agent_id, "job_type": job.job_type, "status": job.status}}


@router.delete("/api/agents/{agent_id}", dependencies=[Depends(require_agents_boundary)])
@router.delete("/webapp/agents/{agent_id}", dependencies=[Depends(require_agents_boundary)])
async def webapp_delete_agent(
    agent_id: int,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    agent = await ensure_agent_admin(agent_id, session, identity)
    deleted = await LinkedAccountService(session).unlink_agent(actor_user_id=identity.user_id, agent_id=agent.id)
    return {"status": "ok" if deleted else "missing", "deleted": deleted}


@router.patch("/api/agents/{agent_id}/safety", dependencies=[Depends(require_agents_boundary)])
@router.patch("/webapp/agents/{agent_id}/safety", dependencies=[Depends(require_agents_boundary)])
async def webapp_update_agent_safety(
    agent_id: int,
    payload: AgentSafetyUpdateRequest,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    agent = await ensure_agent_admin(agent_id, session, identity)
    from datetime import datetime, timezone

    if payload.max_actions_per_hour is not None:
        agent.max_actions_per_hour = payload.max_actions_per_hour
    if payload.max_messages_per_day is not None:
        agent.max_messages_per_day = payload.max_messages_per_day
    if payload.min_delay_seconds is not None:
        agent.min_delay_seconds = payload.min_delay_seconds
    if payload.cooldown_minutes is not None:
        agent.cooldown_minutes = payload.cooldown_minutes
    if payload.safety_mode_enabled is not None:
        agent.safety_mode_enabled = payload.safety_mode_enabled
    if payload.safety_mode_hours is not None:
        agent.safety_mode_until = datetime.now(timezone.utc) if payload.safety_mode_hours > 0 else None
        if payload.safety_mode_hours > 0:
            from datetime import timedelta
            agent.safety_mode_until = datetime.now(timezone.utc) + timedelta(hours=payload.safety_mode_hours)
    await session.commit()
    return {"status": "ok", "agent": serialize_agent(agent)}


@router.get("/api/agents/{agent_id}/leads", dependencies=[Depends(require_agents_boundary)])
@router.get("/webapp/agents/{agent_id}/leads", dependencies=[Depends(require_agents_boundary)])
async def webapp_agent_leads(
    agent_id: int,
    status: str | None = Query(default=None),
    lead_label: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    agent = await ensure_agent_admin(agent_id, session, identity)
    from bot.services.agent_lead_service import AgentLeadService
    return await AgentLeadService(session).list_leads(
        agent_id=agent.id,
        status=status,
        lead_label=lead_label,
        page=page,
        page_size=page_size,
    )


@router.get("/api/agents/{agent_id}/leads/stats", dependencies=[Depends(require_agents_boundary)])
@router.get("/webapp/agents/{agent_id}/leads/stats", dependencies=[Depends(require_agents_boundary)])
async def webapp_agent_lead_stats(
    agent_id: int,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    agent = await ensure_agent_admin(agent_id, session, identity)
    from bot.services.agent_lead_service import AgentLeadService
    return await AgentLeadService(session).lead_stats(agent_id=agent.id)


@router.patch("/api/agents/{agent_id}/leads/{lead_id}", dependencies=[Depends(require_agents_boundary)])
@router.patch("/webapp/agents/{agent_id}/leads/{lead_id}", dependencies=[Depends(require_agents_boundary)])
async def webapp_update_lead(
    agent_id: int,
    lead_id: int,
    payload: LeadUpdateRequest,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_agent_admin(agent_id, session, identity)
    from bot.services.agent_lead_service import AgentLeadService
    lead = await AgentLeadService(session).update_lead(
        lead_id=lead_id,
        status=payload.status,
        assigned_to=payload.assigned_to,
        contact_info=payload.contact_info,
        notes=payload.notes,
        lead_label=payload.lead_label,
        confidence=payload.confidence,
    )
    return {"status": "ok", "lead": AgentLeadService._serialize(lead)}


@router.delete("/api/agents/{agent_id}/leads/{lead_id}", dependencies=[Depends(require_agents_boundary)])
@router.delete("/webapp/agents/{agent_id}/leads/{lead_id}", dependencies=[Depends(require_agents_boundary)])
async def webapp_delete_lead(
    agent_id: int,
    lead_id: int,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_agent_admin(agent_id, session, identity)
    from bot.services.agent_lead_service import AgentLeadService
    await AgentLeadService(session).delete_lead(lead_id=lead_id)
    return {"status": "ok", "deleted": True}


@router.get("/api/agents/{agent_id}/analytics", dependencies=[Depends(require_agents_boundary)])
@router.get("/webapp/agents/{agent_id}/analytics", dependencies=[Depends(require_agents_boundary)])
async def webapp_agent_analytics(
    agent_id: int,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    agent = await ensure_agent_admin(agent_id, session, identity)
    from bot.services.agent_lead_service import AgentLeadService
    from bot.agents.agent_job_service import AgentJobService as JobSvc
    from sqlalchemy import func, select
    from bot.db.models import AgentJob, AgentNotification, AgentLead

    lead_stats = await AgentLeadService(session).lead_stats(agent_id=agent.id)

    total_jobs = (await session.execute(
        select(func.count(AgentJob.id)).where(AgentJob.agent_id == agent.id)
    )).scalar_one()

    completed_jobs = (await session.execute(
        select(func.count(AgentJob.id)).where(AgentJob.agent_id == agent.id, AgentJob.status == "success")
    )).scalar_one()

    failed_jobs = (await session.execute(
        select(func.count(AgentJob.id)).where(AgentJob.agent_id == agent.id, AgentJob.status == "failed")
    )).scalar_one()

    unseen_notifications = (await session.execute(
        select(func.count(AgentNotification.id)).where(
            AgentNotification.agent_id == agent.id,
            AgentNotification.is_seen.is_(False),
        )
    )).scalar_one()

    return {
        "agent": serialize_agent(agent),
        "leads": lead_stats,
        "jobs": {
            "total": total_jobs,
            "completed": completed_jobs,
            "failed": failed_jobs,
            "pending": total_jobs - completed_jobs - failed_jobs,
        },
        "notifications": {
            "unseen": unseen_notifications,
        },
        "safety": {
            "max_actions_per_hour": agent.max_actions_per_hour,
            "min_delay_seconds": agent.min_delay_seconds,
            "cooldown_minutes": agent.cooldown_minutes,
            "safety_mode_enabled": agent.safety_mode_enabled,
            "safety_mode_until": agent.safety_mode_until.isoformat() if agent.safety_mode_until else None,
        },
    }


__all__ = ["router"]
