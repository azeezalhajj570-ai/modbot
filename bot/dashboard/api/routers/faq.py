"""FAQ API router."""

from typing import List, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.session import get_session
from bot.db.models import Group
from bot.services.telegram_webapp_auth import TelegramWebAppIdentity
from bot.faq.service import FAQService
from bot.faq.schemas import (
    FAQSettingsSchema, FAQEntryCreate, FAQEntryUpdate, FAQEntrySchema,
    FAQInteractionSchema, UnansweredQuestionSchema, FAQTestMatchRequest, FAQTestMatchResponse,
    FAQAnswerPayload
)
from ..dependencies import ensure_group_admin, get_identity
from .auth_boundary import require_admin_boundary

router = APIRouter(tags=["faq"], dependencies=[Depends(require_admin_boundary)])

@router.get("/api/groups/{group_id}/faq/settings", response_model=FAQSettingsSchema)
@router.get("/api/admin/groups/{group_id}/faq/settings", response_model=FAQSettingsSchema)
async def get_faq_settings(
    group_id: int,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
):
    await ensure_group_admin(group_id, session, identity)
    service = FAQService(session)
    return await service.get_settings(group_id)

@router.put("/api/groups/{group_id}/faq/settings", response_model=FAQSettingsSchema)
async def update_faq_settings(
    group_id: int,
    payload: FAQSettingsSchema,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
):
    await ensure_group_admin(group_id, session, identity)
    service = FAQService(session)
    settings = await service.update_settings(group_id, **payload.model_dump())
    await session.commit()
    return settings

@router.get("/api/groups/{group_id}/faq/entries", response_model=List[FAQEntrySchema])
@router.get("/api/admin/groups/{group_id}/faq/entries", response_model=List[FAQEntrySchema])
async def get_faq_entries(
    group_id: int,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
):
    await ensure_group_admin(group_id, session, identity)
    service = FAQService(session)
    return await service.get_entries(group_id)

@router.post("/api/groups/{group_id}/faq/entries", response_model=FAQEntrySchema, status_code=status.HTTP_201_CREATED)
async def create_faq_entry(
    group_id: int,
    payload: FAQEntryCreate,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
):
    await ensure_group_admin(group_id, session, identity)
    service = FAQService(session)
    entry = await service.add_entry(
        group_id=group_id, 
        created_by_user_id=identity.user_id,
        **payload.model_dump()
    )
    await session.commit()
    return entry

@router.delete("/api/groups/{group_id}/faq/entries/{entry_id}")
async def delete_faq_entry(
    group_id: int,
    entry_id: int,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
):
    await ensure_group_admin(group_id, session, identity)
    service = FAQService(session)
    success = await service.delete_entry(group_id, entry_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FAQ entry not found")
    await session.commit()
    return {"status": "deleted"}

@router.get("/api/groups/{group_id}/faq/unanswered", response_model=List[UnansweredQuestionSchema])
@router.get("/api/admin/groups/{group_id}/faq/unanswered", response_model=List[UnansweredQuestionSchema])
async def get_unanswered_questions(
    group_id: int,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
):
    await ensure_group_admin(group_id, session, identity)
    service = FAQService(session)
    return await service.get_unanswered_questions(group_id)

@router.post("/api/groups/{group_id}/faq/unanswered/{question_id}/convert", response_model=FAQEntrySchema)
async def convert_unanswered_to_faq(
    group_id: int,
    question_id: int,
    payload: FAQAnswerPayload,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
):
    await ensure_group_admin(group_id, session, identity)
    service = FAQService(session)
    entry = await service.convert_to_faq(group_id, question_id, payload.answer)
    await session.commit()
    return entry

@router.post("/api/groups/{group_id}/faq/test-match", response_model=FAQTestMatchResponse)
async def test_faq_match(
    group_id: int,
    payload: FAQTestMatchRequest,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
):
    await ensure_group_admin(group_id, session, identity)
    service = FAQService(session)
    entries = await service.get_entries(group_id, enabled_only=True)
    match_result = service.matcher.match(payload.question, entries)
    return {
        "matched": match_result.faq_entry_id is not None,
        "confidence": match_result.confidence,
        "entry_id": match_result.faq_entry_id,
        "answer": match_result.answer
    }


@router.post("/api/groups/{group_id}/faq/ai-analyze")
async def ai_analyze_messages(
    group_id: int,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
    max_messages: int = 1000,
):
    await ensure_group_admin(group_id, session, identity)
    from sqlalchemy import select as sa_select
    group = (await session.execute(
        sa_select(Group).where(Group.id == group_id)
    )).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    from bot.services.message_analyzer import analyze_group_messages
    result = await analyze_group_messages(
        session, tg_group_id=group.tg_group_id, max_messages=max_messages,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=str(result["error"]))
    return result
