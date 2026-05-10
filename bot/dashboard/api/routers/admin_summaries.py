from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import DailyGroupSummary, Group, GroupSummarySettings
from bot.db.session import get_session
from bot.summaries.service import DailyAdminSummaryService
from bot.services.telegram_webapp_auth import TelegramWebAppIdentity

from ..dependencies import ensure_group_admin, get_identity
from .auth_boundary import require_admin_boundary

router = APIRouter(tags=["admin-summaries"], dependencies=[Depends(require_admin_boundary)])


class SummarySettingsPayload(BaseModel):
    enabled: bool = False
    summary_time: str = Field(default="21:00", pattern=r"^\d{2}:\d{2}$")
    timezone: str = "Asia/Aden"
    delivery_mode: str = "dashboard_only"
    admin_chat_id: int | None = None
    include_top_users: bool = True
    include_links: bool = True
    include_moderation_events: bool = True
    include_unanswered_questions: bool = True
    include_recommendations: bool = True
    max_message_samples: int = Field(default=500, ge=10, le=5000)


class GenerateSummaryPayload(BaseModel):
    summary_date: date | None = None
    deliver: bool = False


def _serialize_settings(settings: GroupSummarySettings) -> dict[str, Any]:
    return {
        "id": settings.id,
        "group_id": settings.group_id,
        "enabled": settings.enabled,
        "summary_time": settings.summary_time,
        "timezone": settings.timezone,
        "delivery_mode": settings.delivery_mode,
        "admin_chat_id": settings.admin_chat_id,
        "include_top_users": settings.include_top_users,
        "include_links": settings.include_links,
        "include_moderation_events": settings.include_moderation_events,
        "include_unanswered_questions": settings.include_unanswered_questions,
        "include_recommendations": settings.include_recommendations,
        "max_message_samples": settings.max_message_samples,
        "created_at": settings.created_at.isoformat() if settings.created_at else None,
        "updated_at": settings.updated_at.isoformat() if settings.updated_at else None,
    }


def _serialize_summary(summary: DailyGroupSummary) -> dict[str, Any]:
    return {
        "id": summary.id,
        "group_id": summary.group_id,
        "summary_date": summary.summary_date.isoformat(),
        "total_messages": summary.total_messages,
        "active_users_count": summary.active_users_count,
        "links_count": summary.links_count,
        "suspicious_messages_count": summary.suspicious_messages_count,
        "deleted_messages_count": summary.deleted_messages_count,
        "top_users": summary.top_users,
        "top_topics": summary.top_topics,
        "important_questions": summary.important_questions,
        "unanswered_questions": summary.unanswered_questions,
        "links": summary.links,
        "moderation_highlights": summary.moderation_highlights,
        "recommendations": summary.recommendations,
        "summary_text": summary.summary_text,
        "status": summary.status,
        "error_message": summary.error_message,
        "created_at": summary.created_at.isoformat() if summary.created_at else None,
        "updated_at": summary.updated_at.isoformat() if summary.updated_at else None,
    }


@router.get("/api/admin/groups/{group_id}/summaries/settings")
@router.get("/webapp/groups/{group_id}/summaries/settings")
async def get_group_summary_settings(
    group_id: int,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_group_admin(group_id, session, identity)
    settings = await DailyAdminSummaryService(session).get_settings(group_id)
    await session.commit()
    await session.refresh(settings)
    return _serialize_settings(settings)


@router.put("/api/admin/groups/{group_id}/summaries/settings")
@router.put("/webapp/groups/{group_id}/summaries/settings")
async def put_group_summary_settings(
    group_id: int,
    payload: SummarySettingsPayload,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_group_admin(group_id, session, identity)
    settings = await DailyAdminSummaryService(session).update_settings(group_id, payload.model_dump())
    return _serialize_settings(settings)


@router.get("/api/admin/groups/{group_id}/summaries")
@router.get("/webapp/groups/{group_id}/summaries")
async def list_group_summaries(
    group_id: int,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    await ensure_group_admin(group_id, session, identity)
    summaries = await DailyAdminSummaryService(session).list_summaries(group_id)
    return [_serialize_summary(summary) for summary in summaries]


@router.get("/api/admin/groups/{group_id}/summaries/{summary_id}")
@router.get("/webapp/groups/{group_id}/summaries/{summary_id}")
async def get_group_summary(
    group_id: int,
    summary_id: int,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_group_admin(group_id, session, identity)
    summary = (
        await session.execute(
            select(DailyGroupSummary).where(DailyGroupSummary.group_id == group_id, DailyGroupSummary.id == summary_id)
        )
    ).scalar_one_or_none()
    if summary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Summary not found")
    return _serialize_summary(summary)


@router.post("/api/admin/groups/{group_id}/summaries/generate")
@router.post("/webapp/groups/{group_id}/summaries/generate")
async def generate_group_summary(
    group_id: int,
    payload: GenerateSummaryPayload,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_group_admin(group_id, session, identity)
    group = (await session.execute(select(Group).where(Group.id == group_id))).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    summary = await DailyAdminSummaryService(session).generate_summary_for_group(
        group_id,
        payload.summary_date or date.today(),
        deliver=payload.deliver,
    )
    return _serialize_summary(summary)
