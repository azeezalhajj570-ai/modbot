"""Scraper API endpoints for groups/channels scraping operations."""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.agents.jobs import SCRAPER_FULL_GROUP_JOB_TYPE, SCRAPER_GROUP_INFO_JOB_TYPE, SCRAPER_MEMBERS_JOB_TYPE, SCRAPER_MESSAGES_JOB_TYPE
from bot.agents.dispatch import dispatch_agent_job
from bot.config import get_settings
from bot.db.models import Agent, AgentJob, Group, GroupKnowledge, ScrapedConversation, ScrapedDailySummary, ScrapedGroup, ScrapedLead, ScrapedMember, ScrapedMessage
from bot.db.session import get_session
from bot.agents.service import AgentService
from bot.services.group_service import canonical_tg_group_id, tg_group_id_candidates
from bot.services.permission_service import PermissionService
from bot.services.scraper_service import ScraperService
from bot.dashboard.api.auth import extract_dashboard_identity
from bot.services.telegram_webapp_auth import TelegramWebAppAuthError, TelegramWebAppIdentity
from datetime import datetime

router = APIRouter(prefix="/webapp/scraper", tags=["scraper"])


class ScrapeGroupInfoRequest(BaseModel):
    agent_id: int
    tg_group_id: int


class ScrapeMembersRequest(BaseModel):
    agent_id: int
    tg_group_id: int
    member_limit: int = Field(default=1000, ge=1, le=10000)


class ScrapeMessagesRequest(BaseModel):
    agent_id: int
    tg_group_id: int
    message_limit: int = Field(default=100, ge=1, le=20000)
    max_age_days: int | None = Field(default=None, ge=1, le=3650)
    scan_strategy: str = Field(default="auto", description="auto, checkpoint, full")


class ScrapeFullGroupRequest(BaseModel):
    agent_id: int
    tg_group_id: int
    scrape_members: bool = True
    scrape_messages: bool = True
    member_limit: int = Field(default=1000, ge=1, le=10000)
    message_limit: int = Field(default=100, ge=1, le=20000)
    max_age_days: int | None = Field(default=None, ge=1, le=3650)
    scan_strategy: str = Field(default="auto", description="auto, checkpoint, full")


class ScrapeJobResponse(BaseModel):
    job_id: int
    status: str
    message: str


async def get_identity(
    identity: TelegramWebAppIdentity = Depends(extract_dashboard_identity),
) -> TelegramWebAppIdentity:
    return identity


async def _ensure_agent_access(
    *,
    agent_id: int,
    session: AsyncSession,
    identity: TelegramWebAppIdentity,
) -> Agent:
    agent = (await session.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    can_manage = await PermissionService(session).can(agent.group_id, identity.user_id, "group.settings.update")
    if not can_manage:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")
    return agent


async def _ensure_scraped_group_access(
    *,
    scraped_group: ScrapedGroup,
    session: AsyncSession,
    identity: TelegramWebAppIdentity,
) -> None:
    candidate_group_ids = tg_group_id_candidates(int(scraped_group.tg_group_id))
    groups = (
        await session.execute(select(Group).where(Group.tg_group_id.in_(candidate_group_ids)))
    ).scalars().all()
    if not groups:
        if scraped_group.last_agent_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mapped managed group not found")
        active_agents = await AgentService(session).list_all_active_agents(actor_user_id=identity.user_id)
        if any(int(agent.id) == int(scraped_group.last_agent_id) for agent in active_agents):
            return
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mapped managed group not found")

    permission_service = PermissionService(session)
    canonical_id = canonical_tg_group_id(int(scraped_group.tg_group_id))
    ordered_groups = sorted(
        groups,
        key=lambda group: (
            0 if int(group.tg_group_id) == canonical_id else 1,
            0 if int(group.tg_group_id) == int(scraped_group.tg_group_id) else 1,
            int(group.id),
        ),
    )
    for group in ordered_groups:
        can_manage = await permission_service.can(group.id, identity.user_id, "group.settings.update")
        if can_manage:
            return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")


@router.post("/scrape/group-info", response_model=ScrapeJobResponse)
async def scrape_group_info(
    request: ScrapeGroupInfoRequest,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> ScrapeJobResponse:
    """
    Start a job to scrape basic group/channel info.
    Runs asynchronously via agent worker.
    """
    # Verify agent exists and user has permission
    await _ensure_agent_access(agent_id=request.agent_id, session=session, identity=identity)

    # Create job record
    job = AgentJob(
        agent_id=request.agent_id,
        job_type=SCRAPER_GROUP_INFO_JOB_TYPE,
        job_payload={
            "tg_group_id": request.tg_group_id,
        },
        status="pending",
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    # Dispatch job to worker
    await dispatch_agent_job(job.id)

    return ScrapeJobResponse(
        job_id=job.id,
        status=job.status,
        message="Scraping job dispatched successfully",
    )


@router.post("/scrape/members", response_model=ScrapeJobResponse)
async def scrape_members(
    request: ScrapeMembersRequest,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> ScrapeJobResponse:
    """
    Start a job to scrape group/channel members.
    Runs asynchronously via agent worker.
    """
    await _ensure_agent_access(agent_id=request.agent_id, session=session, identity=identity)

    job = AgentJob(
        agent_id=request.agent_id,
        job_type=SCRAPER_MEMBERS_JOB_TYPE,
        job_payload={
            "tg_group_id": request.tg_group_id,
            "member_limit": request.member_limit,
        },
        status="pending",
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    await dispatch_agent_job(job.id)

    return ScrapeJobResponse(
        job_id=job.id,
        status=job.status,
        message="Member scraping job dispatched successfully",
    )


@router.post("/scrape/messages", response_model=ScrapeJobResponse)
async def scrape_messages(
    request: ScrapeMessagesRequest,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> ScrapeJobResponse:
    """
    Start a job to scrape group/channel messages.
    Runs asynchronously via agent worker.
    """
    await _ensure_agent_access(agent_id=request.agent_id, session=session, identity=identity)

    job = AgentJob(
        agent_id=request.agent_id,
        job_type=SCRAPER_MESSAGES_JOB_TYPE,
        job_payload={
            "tg_group_id": request.tg_group_id,
            "message_limit": request.message_limit,
            "max_age_days": request.max_age_days,
            "scan_strategy": request.scan_strategy,
        },
        status="pending",
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    await dispatch_agent_job(job.id)

    return ScrapeJobResponse(
        job_id=job.id,
        status=job.status,
        message="Message scraping job dispatched successfully",
    )


@router.post("/scrape/full-group", response_model=ScrapeJobResponse)
async def scrape_full_group(
    request: ScrapeFullGroupRequest,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> ScrapeJobResponse:
    """
    Start a job to scrape both members and messages from a group/channel.
    Runs asynchronously via agent worker.
    """
    await _ensure_agent_access(agent_id=request.agent_id, session=session, identity=identity)

    job = AgentJob(
        agent_id=request.agent_id,
        job_type=SCRAPER_FULL_GROUP_JOB_TYPE,
        job_payload={
            "tg_group_id": request.tg_group_id,
            "scrape_members": request.scrape_members,
            "scrape_messages": request.scrape_messages,
            "member_limit": request.member_limit,
            "message_limit": request.message_limit,
            "max_age_days": request.max_age_days,
            "scan_strategy": request.scan_strategy,
        },
        status="pending",
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    await dispatch_agent_job(job.id)

    return ScrapeJobResponse(
        job_id=job.id,
        status=job.status,
        message="Full group scraping job dispatched successfully",
    )


@router.get("/groups")
async def list_scraped_groups(
    tg_group_id: int | None = Query(default=None),
    agent_id: int | None = Query(default=None),
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """List all scraped groups/channels."""
    member_total = (
        select(func.count(ScrapedMember.id))
        .where(ScrapedMember.scraped_group_id == ScrapedGroup.id)
        .correlate(ScrapedGroup)
        .scalar_subquery()
    )
    message_total = (
        select(func.count(ScrapedMessage.id))
        .where(ScrapedMessage.scraped_group_id == ScrapedGroup.id)
        .correlate(ScrapedGroup)
        .scalar_subquery()
    )
    stmt = select(
        ScrapedGroup,
        member_total.label("members_total"),
        message_total.label("messages_total"),
    )
    if tg_group_id is not None:
        stmt = stmt.where(ScrapedGroup.tg_group_id == canonical_tg_group_id(int(tg_group_id)))
    if agent_id is not None:
        stmt = stmt.where(ScrapedGroup.last_agent_id == int(agent_id))
    stmt = stmt.order_by(ScrapedGroup.updated_at.desc())
    result = await session.execute(stmt)
    rows = result.all()
    filtered_groups: list[tuple[ScrapedGroup, int, int]] = []
    for group, members_total, messages_total in rows:
        try:
            await _ensure_scraped_group_access(scraped_group=group, session=session, identity=identity)
        except HTTPException:
            continue
        filtered_groups.append((group, int(members_total or 0), int(messages_total or 0)))

    return [
        {
            "id": group.id,
            "tg_group_id": group.tg_group_id,
            "last_agent_id": group.last_agent_id,
            "title": group.title,
            "username": group.username,
            "group_type": group.group_type,
            "member_count": group.member_count,
            "description": group.description,
            "members_total": members_total,
            "messages_total": messages_total,
            "created_at": group.created_at.isoformat() if group.created_at else None,
            "updated_at": group.updated_at.isoformat() if group.updated_at else None,
        }
        for group, members_total, messages_total in filtered_groups
    ]


@router.get("/groups/{group_id}")
async def get_scraped_group(
    group_id: int,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get details of a scraped group."""
    group = (await session.execute(select(ScrapedGroup).where(ScrapedGroup.id == group_id))).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scraped group not found")
    await _ensure_scraped_group_access(scraped_group=group, session=session, identity=identity)

    return {
        "id": group.id,
        "tg_group_id": group.tg_group_id,
        "last_agent_id": group.last_agent_id,
        "title": group.title,
        "username": group.username,
        "group_type": group.group_type,
        "member_count": group.member_count,
        "description": group.description,
        "created_at": group.created_at.isoformat() if group.created_at else None,
        "updated_at": group.updated_at.isoformat() if group.updated_at else None,
    }


@router.get("/groups/{group_id}/members")
async def get_scraped_members(
    group_id: int,
    page: int = 1,
    page_size: int = 50,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get scraped members of a group."""
    scraped_group = (await session.execute(select(ScrapedGroup).where(ScrapedGroup.id == group_id))).scalar_one_or_none()
    if scraped_group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scraped group not found")
    await _ensure_scraped_group_access(scraped_group=scraped_group, session=session, identity=identity)

    offset = (page - 1) * page_size

    stmt = (
        select(ScrapedMember)
        .where(ScrapedMember.scraped_group_id == group_id)
        .order_by(ScrapedMember.scraped_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    result = await session.execute(stmt)
    members = result.scalars().all()

    # Get total count
    count_stmt = select(func.count(ScrapedMember.id)).where(ScrapedMember.scraped_group_id == group_id)
    total = int((await session.execute(count_stmt)).scalar_one() or 0)

    return {
        "members": [
            {
                "id": member.id,
                "tg_user_id": member.tg_user_id,
                "username": member.username,
                "first_name": member.first_name,
                "last_name": member.last_name,
                "full_name": member.full_name,
                "phone": member.phone,
                "is_bot": member.is_bot,
                "is_premium": member.is_premium,
                "role": member.role,
                "joined_date": member.joined_date.isoformat() if member.joined_date else None,
                "scraped_at": member.scraped_at.isoformat() if member.scraped_at else None,
            }
            for member in members
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/groups/{group_id}/messages")
async def get_scraped_messages(
    group_id: int,
    page: int = 1,
    page_size: int = 50,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get scraped messages of a group."""
    scraped_group = (await session.execute(select(ScrapedGroup).where(ScrapedGroup.id == group_id))).scalar_one_or_none()
    if scraped_group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scraped group not found")
    await _ensure_scraped_group_access(scraped_group=scraped_group, session=session, identity=identity)

    offset = (page - 1) * page_size

    stmt = (
        select(ScrapedMessage)
        .where(ScrapedMessage.scraped_group_id == group_id)
        .order_by(ScrapedMessage.message_date.desc())
        .offset(offset)
        .limit(page_size)
    )
    result = await session.execute(stmt)
    messages = result.scalars().all()

    # Get total count
    count_stmt = select(func.count(ScrapedMessage.id)).where(ScrapedMessage.scraped_group_id == group_id)
    total = int((await session.execute(count_stmt)).scalar_one() or 0)

    return {
        "messages": [
            {
                "id": message.id,
                "message_id": message.message_id,
                "sender_user_id": message.sender_user_id,
                "sender_username": message.sender_username,
                "sender_first_name": message.sender_first_name,
                "sender_last_name": message.sender_last_name,
                "message_text": message.message_text,
                "message_date": message.message_date.isoformat() if message.message_date else None,
                "message_type": message.message_type,
                "media_file_id": message.media_file_id,
                "media_url": message.media_url,
                "reply_to_message_id": message.reply_to_message_id,
                "forward_from_user_id": message.forward_from_user_id,
                "scraped_at": message.scraped_at.isoformat() if message.scraped_at else None,
            }
            for message in messages
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/groups/{group_id}/conversations")
async def list_scraped_conversations(
    group_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    identity: TelegramWebAppIdentity = Depends(get_identity),
) -> dict[str, Any]:
    group = (await session.execute(select(ScrapedGroup).where(ScrapedGroup.id == group_id))).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="Scraped group not found")
    offset = (page - 1) * page_size
    total = (await session.execute(select(func.count(ScrapedConversation.id)).where(
        ScrapedConversation.scraped_group_id == group_id,
    ))).scalar_one()
    rows = (await session.execute(
        select(ScrapedConversation).where(
            ScrapedConversation.scraped_group_id == group_id,
        ).order_by(desc(ScrapedConversation.last_message_at)).offset(offset).limit(page_size)
    )).scalars().all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "conversations": [{
            "id": c.id,
            "root_message_id": c.root_message_id,
            "title": c.title,
            "root_sender_name": c.root_sender_name,
            "participant_count": c.participant_count,
            "message_count": c.message_count,
            "first_message_at": c.first_message_at.isoformat() if c.first_message_at else None,
            "last_message_at": c.last_message_at.isoformat() if c.last_message_at else None,
            "is_topic": c.is_topic,
        } for c in rows],
    }


@router.get("/groups/{group_id}/conversations/{conv_id}/messages")
async def get_conversation_messages(
    group_id: int,
    conv_id: int,
    session: AsyncSession = Depends(get_session),
    identity: TelegramWebAppIdentity = Depends(get_identity),
) -> list[dict[str, Any]]:
    conv = (await session.execute(select(ScrapedConversation).where(
        ScrapedConversation.id == conv_id,
        ScrapedConversation.scraped_group_id == group_id,
    ))).scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    root_id = conv.root_message_id
    messages = (await session.execute(
        select(ScrapedMessage).where(
            ScrapedMessage.scraped_group_id == group_id,
            (ScrapedMessage.message_id == root_id) | (ScrapedMessage.reply_to_message_id == root_id) | (ScrapedMessage.reply_to_top_id == root_id),
        ).order_by(ScrapedMessage.message_date.asc())
    )).scalars().all()
    return [{
        "id": m.id,
        "message_id": m.message_id,
        "sender_user_id": m.sender_user_id,
        "sender_username": m.sender_username,
        "sender_first_name": m.sender_first_name,
        "message_text": m.message_text,
        "message_type": m.message_type,
        "message_date": m.message_date.isoformat() if m.message_date else None,
        "reply_to_message_id": m.reply_to_message_id,
        "reply_to_top_id": m.reply_to_top_id,
    } for m in messages]


class ExtractKnowledgeRequest(BaseModel):
    max_messages: int = Field(default=2000, ge=100, le=10000)


@router.post("/groups/{group_id}/extract-knowledge")
async def extract_group_knowledge(
    group_id: int,
    request: ExtractKnowledgeRequest = ExtractKnowledgeRequest(),
    session: AsyncSession = Depends(get_session),
    identity: TelegramWebAppIdentity = Depends(get_identity),
) -> dict[str, Any]:
    group = (await session.execute(select(ScrapedGroup).where(ScrapedGroup.id == group_id))).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="Scraped group not found")
    await _ensure_scraped_group_access(scraped_group=group, session=session, identity=identity)

    from bot.services.knowledge_extractor import KnowledgeExtractor
    extractor = KnowledgeExtractor(session)
    result = await extractor.extract_knowledge(scraped_group_id=group_id, max_messages=request.max_messages)
    return result


@router.get("/groups/{group_id}/knowledge")
async def list_group_knowledge(
    group_id: int,
    knowledge_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    identity: TelegramWebAppIdentity = Depends(get_identity),
) -> dict[str, Any]:
    group = (await session.execute(select(ScrapedGroup).where(ScrapedGroup.id == group_id))).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="Scraped group not found")
    await _ensure_scraped_group_access(scraped_group=group, session=session, identity=identity)

    stmt = select(GroupKnowledge).where(GroupKnowledge.scraped_group_id == group_id)
    if knowledge_type:
        stmt = stmt.where(GroupKnowledge.knowledge_type == knowledge_type)
    stmt = stmt.order_by(GroupKnowledge.confidence.desc()).offset((page - 1) * page_size).limit(page_size)

    rows = (await session.execute(stmt)).scalars().all()
    total = (await session.execute(
        select(func.count(GroupKnowledge.id)).where(GroupKnowledge.scraped_group_id == group_id)
    )).scalar_one()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [{
            "id": k.id,
            "knowledge_type": k.knowledge_type,
            "title": k.title,
            "content": k.content,
            "confidence": k.confidence,
            "first_seen": k.first_seen.isoformat() if k.first_seen else None,
            "last_updated": k.last_updated.isoformat() if k.last_updated else None,
        } for k in rows],
    }


@router.get("/groups/{group_id}/daily-summaries")
async def list_daily_summaries(
    group_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    identity: TelegramWebAppIdentity = Depends(get_identity),
) -> dict[str, Any]:
    group = (await session.execute(select(ScrapedGroup).where(ScrapedGroup.id == group_id))).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="Scraped group not found")

    stmt = (
        select(ScrapedDailySummary)
        .where(ScrapedDailySummary.scraped_group_id == group_id)
        .order_by(ScrapedDailySummary.date.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await session.execute(stmt)).scalars().all()
    total = (await session.execute(
        select(func.count(ScrapedDailySummary.id)).where(ScrapedDailySummary.scraped_group_id == group_id)
    )).scalar_one()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [{
            "id": s.id,
            "date": s.date.isoformat() if s.date else None,
            "message_count": s.message_count,
            "active_users": s.active_users,
            "top_topics": s.top_topics,
            "summary": s.summary,
        } for s in rows],
    }


# ─── Search ────────────────────────────────────────────────────────────────


@router.get("/groups/{group_id}/search")
async def search_messages(
    group_id: int,
    query: str = Query(default="", description="Search term (case-insensitive substring match)"),
    sender_user_id: int | None = Query(default=None),
    message_type: str | None = Query(default=None),
    date_from: str | None = Query(default=None, description="ISO date, e.g. 2026-01-01"),
    date_to: str | None = Query(default=None, description="ISO date, e.g. 2026-04-30"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    identity: TelegramWebAppIdentity = Depends(get_identity),
) -> dict[str, Any]:
    group = (await session.execute(select(ScrapedGroup).where(ScrapedGroup.id == group_id))).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="Scraped group not found")
    await _ensure_scraped_group_access(scraped_group=group, session=session, identity=identity)

    parsed_from = datetime.fromisoformat(date_from) if date_from else None
    parsed_to = datetime.fromisoformat(date_to) if date_to else None

    service = ScraperService(session)
    return await service.search_messages(
        tg_group_id=int(group.tg_group_id),
        query=query,
        sender_user_id=sender_user_id,
        message_type=message_type,
        date_from=parsed_from,
        date_to=parsed_to,
        page=page,
        page_size=page_size,
    )


# ─── Export ────────────────────────────────────────────────────────────────


@router.get("/groups/{group_id}/export")
async def export_group_data(
    group_id: int,
    format: str = Query(default="json", description="json or csv"),
    data_type: str = Query(default="messages", description="messages, members, or conversations"),
    limit: int = Query(default=10000, ge=1, le=100000),
    session: AsyncSession = Depends(get_session),
    identity: TelegramWebAppIdentity = Depends(get_identity),
):
    group = (await session.execute(select(ScrapedGroup).where(ScrapedGroup.id == group_id))).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="Scraped group not found")
    await _ensure_scraped_group_access(scraped_group=group, session=session, identity=identity)

    service = ScraperService(session)
    data = await service.export_group_data(
        tg_group_id=int(group.tg_group_id),
        format=format,
        data_type=data_type,
        limit=limit,
    )

    media_type = "text/csv" if format == "csv" else "application/json"
    filename = f"{data_type}_{group.tg_group_id}.{format}"
    return Response(content=data, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ─── Member Leaderboard ────────────────────────────────────────────────────


@router.get("/groups/{group_id}/leaderboard")
async def member_leaderboard(
    group_id: int,
    limit: int = Query(default=50, ge=1, le=500),
    days: int = Query(default=30, ge=1, le=365),
    session: AsyncSession = Depends(get_session),
    identity: TelegramWebAppIdentity = Depends(get_identity),
) -> dict[str, Any]:
    group = (await session.execute(select(ScrapedGroup).where(ScrapedGroup.id == group_id))).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="Scraped group not found")
    await _ensure_scraped_group_access(scraped_group=group, session=session, identity=identity)

    service = ScraperService(session)
    leaderboard = await service.get_member_leaderboard(
        tg_group_id=int(group.tg_group_id),
        limit=limit,
        days=days,
    )
    return {"leaderboard": leaderboard, "total_active": len(leaderboard)}


# ─── Lead CRM ──────────────────────────────────────────────────────────────


@router.post("/groups/{group_id}/extract-leads")
async def extract_leads_endpoint(
    group_id: int,
    limit: int | None = Query(default=500),
    session: AsyncSession = Depends(get_session),
    identity: TelegramWebAppIdentity = Depends(get_identity),
) -> dict[str, Any]:
    group = (await session.execute(select(ScrapedGroup).where(ScrapedGroup.id == group_id))).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="Scraped group not found")
    await _ensure_scraped_group_access(scraped_group=group, session=session, identity=identity)

    service = ScraperService(session)
    return await service.extract_leads(tg_group_id=int(group.tg_group_id), limit=limit)


@router.get("/groups/{group_id}/leads")
async def list_leads(
    group_id: int,
    status: str | None = Query(default=None, description="new, contacted, converted, dismissed"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    identity: TelegramWebAppIdentity = Depends(get_identity),
) -> dict[str, Any]:
    group = (await session.execute(select(ScrapedGroup).where(ScrapedGroup.id == group_id))).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="Scraped group not found")
    await _ensure_scraped_group_access(scraped_group=group, session=session, identity=identity)

    service = ScraperService(session)
    return await service.list_leads(tg_group_id=int(group.tg_group_id), status=status, page=page, page_size=page_size)


class UpdateLeadRequest(BaseModel):
    status: str = Field(description="new, contacted, converted, dismissed")
    notes: str | None = None


@router.patch("/groups/{group_id}/leads/{lead_id}")
async def update_lead(
    group_id: int,
    lead_id: int,
    request: UpdateLeadRequest,
    session: AsyncSession = Depends(get_session),
    identity: TelegramWebAppIdentity = Depends(get_identity),
) -> dict[str, str]:
    group = (await session.execute(select(ScrapedGroup).where(ScrapedGroup.id == group_id))).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="Scraped group not found")

    lead = (await session.execute(select(ScrapedLead).where(ScrapedLead.id == lead_id))).scalar_one_or_none()
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    lead.status = request.status
    if request.notes:
        lead.notes = request.notes
    await session.commit()
    return {"status": "ok"}


# ─── Engagement Nudges ────────────────────────────────────────────────────


@router.get("/groups/{group_id}/nudges")
async def get_nudges(
    group_id: int,
    session: AsyncSession = Depends(get_session),
    identity: TelegramWebAppIdentity = Depends(get_identity),
) -> dict[str, Any]:
    group = (await session.execute(select(ScrapedGroup).where(ScrapedGroup.id == group_id))).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="Scraped group not found")
    await _ensure_scraped_group_access(scraped_group=group, session=session, identity=identity)

    service = ScraperService(session)
    return await service.get_nudge_suggestions(tg_group_id=int(group.tg_group_id))
