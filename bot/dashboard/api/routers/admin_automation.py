from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from bot.agents.dispatch import dispatch_agent_job
from bot.core.runtime.admin import AdminAutomationRuntimeService
from bot.db.session import get_session
from bot.services.telegram_webapp_auth import TelegramWebAppIdentity
from bot.workers.tasks import (
    schedule_bot_message_delete,
    schedule_scheduled_announcement,
    schedule_task_follow_up,
)

from ..dependencies import check_plan_limit, ensure_group_admin, get_identity
from ._shared import (
    ScheduledMessagePatchRequest,
    ScheduledMessageRequest,
    TaskAssignmentPatchRequest,
    TaskAssignmentRequest,
)

from aiogram import Bot
from bot.config import get_settings

router = APIRouter(tags=["admin"])


async def get_bot() -> Bot:
    bot = Bot(token=get_settings().bot_token)
    try:
        yield bot
    finally:
        await bot.session.close()


def _runtime(session: AsyncSession, bot: Bot | None = None) -> AdminAutomationRuntimeService:
    return AdminAutomationRuntimeService(
        session,
        dispatch_agent_job=dispatch_agent_job,
        dispatch_follow_up=schedule_task_follow_up,
        dispatch_delete_message=schedule_bot_message_delete,
        schedule_announcement=schedule_scheduled_announcement,
        bot=bot,
    )


@router.get("/api/admin/tasks/catalog")
@router.get("/webapp/tasks/catalog")
async def webapp_task_catalog(
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
    bot: Bot = Depends(get_bot),
) -> list[dict]:
    _ = identity
    return await _runtime(session, bot).list_task_catalog()


@router.get("/api/admin/groups/{group_id}/tasks")
@router.get("/webapp/groups/{group_id}/tasks")
async def webapp_group_tasks(
    group_id: int,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
    bot: Bot = Depends(get_bot),
) -> list[dict]:
    try:
        return await _runtime(session, bot).list_assignments(actor_user_id=identity.user_id, group_id=group_id)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.post("/api/admin/groups/{group_id}/tasks")
@router.post("/webapp/groups/{group_id}/tasks")
async def webapp_save_group_task(
    group_id: int,
    payload: TaskAssignmentRequest,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
    bot: Bot = Depends(get_bot),
) -> dict[str, object]:
    await ensure_group_admin(group_id, session, identity)
    try:
        from bot.services.task_assignment_store import TaskAssignmentStore
        assignments = await TaskAssignmentStore(session).list_assignments(group_id=group_id)
        await check_plan_limit(session, identity, "automation_tasks", len(assignments))
        assignment = await _runtime(session, bot).save_assignment(
            actor_user_id=identity.user_id,
            group_id=group_id,
            assignment_id=payload.assignment_id,
            task_key=payload.task_key,
            executor_type=payload.executor_type,
            enabled=payload.enabled,
            conditions=payload.conditions,
            config=payload.config,
            agent_id=payload.agent_id,
            group_ids=payload.group_ids,
            group_tg_ids=payload.group_tg_ids,
            group_titles=payload.group_titles,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return {"status": "ok", "assignment": assignment}


@router.patch("/api/admin/groups/{group_id}/tasks/{assignment_id}")
@router.patch("/webapp/groups/{group_id}/tasks/{assignment_id}")
async def webapp_update_group_task(
    group_id: int,
    assignment_id: str,
    payload: TaskAssignmentPatchRequest,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
    bot: Bot = Depends(get_bot),
) -> dict[str, object]:
    try:
        existing_list = await _runtime(session, bot).list_assignments(
            actor_user_id=identity.user_id, group_id=group_id,
        )
        found = next((a for a in existing_list if a["assignment_id"] == assignment_id), None)
        if not found:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

        assignment = await _runtime(session, bot).save_assignment(
            actor_user_id=identity.user_id,
            group_id=group_id,
            assignment_id=assignment_id,
            task_key=payload.task_key if payload.task_key is not None else found["task_key"],
            executor_type=payload.executor_type if payload.executor_type is not None else found["executor_type"],
            enabled=payload.enabled if payload.enabled is not None else found["enabled"],
            conditions=payload.conditions if payload.conditions is not None else found["conditions"],
            config=payload.config if payload.config is not None else found["config"],
            agent_id=payload.agent_id if payload.agent_id is not None else found.get("agent_id"),
            group_ids=payload.group_ids if payload.group_ids is not None else found.get("group_ids", []),
            group_tg_ids=payload.group_tg_ids if payload.group_tg_ids is not None else found.get("group_tg_ids", []),
            group_titles=payload.group_titles if payload.group_titles is not None else found.get("group_titles", []),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return {"status": "ok", "assignment": assignment}


@router.delete("/api/admin/groups/{group_id}/tasks/{assignment_id}")
@router.delete("/webapp/groups/{group_id}/tasks/{assignment_id}")
async def webapp_delete_group_task(
    group_id: int,
    assignment_id: str,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
    bot: Bot = Depends(get_bot),
) -> dict[str, object]:
    try:
        deleted = await _runtime(session, bot).delete_assignment(
            actor_user_id=identity.user_id,
            group_id=group_id,
            assignment_id=assignment_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return {"status": "ok" if deleted else "missing", "deleted": deleted}


@router.get("/api/admin/groups/{group_id}/scheduled-messages")
@router.get("/webapp/groups/{group_id}/scheduled-messages")
async def webapp_group_scheduled_messages(
    group_id: int,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
    bot: Bot = Depends(get_bot),
) -> list[dict]:
    await ensure_group_admin(group_id, session, identity)
    return await _runtime(session, bot).list_scheduled_messages(group_id=group_id)


@router.post("/api/admin/groups/{group_id}/scheduled-messages")
@router.post("/webapp/groups/{group_id}/scheduled-messages")
async def webapp_create_scheduled_message(
    group_id: int,
    payload: ScheduledMessageRequest,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
    bot: Bot = Depends(get_bot),
) -> dict[str, object]:
    await ensure_group_admin(group_id, session, identity)
    try:
        from bot.services.scheduled_message_service import ScheduledMessageService
        svc = ScheduledMessageService(session)
        existing = await svc.list_entries(group_id=group_id)
        current_count = len([e for e in existing if e.get("status") == "pending"])
        await check_plan_limit(session, identity, "scheduled_messages", current_count)
        entry = await _runtime(session, bot).create_scheduled_message(
            actor_user_id=identity.user_id,
            group_id=group_id,
            text=payload.text,
            schedule=payload.schedule,
            delete_after_seconds=payload.delete_after_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return {"status": "ok", "scheduled_message": entry}


@router.patch("/api/admin/groups/{group_id}/scheduled-messages/{entry_id}")
@router.patch("/webapp/groups/{group_id}/scheduled-messages/{entry_id}")
async def webapp_update_scheduled_message(
    group_id: int,
    entry_id: str,
    payload: ScheduledMessagePatchRequest,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
    bot: Bot = Depends(get_bot),
) -> dict[str, object]:
    await ensure_group_admin(group_id, session, identity)
    try:
        from bot.services.scheduled_message_service import ScheduledMessageService
        svc = ScheduledMessageService(session)
        existing = await svc.get_entry(group_id=group_id, entry_id=entry_id)
        if not existing:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scheduled message not found")

        text = payload.text if payload.text is not None else existing["text"]

        if payload.schedule is not None:
            schedule = payload.schedule
        elif existing.get("cron"):
            schedule = existing["cron"]
        else:
            schedule = existing["send_at"].replace("T", " ")

        delete_after_seconds = payload.delete_after_seconds if payload.delete_after_seconds is not None else existing.get("delete_after_seconds")

        entry = await _runtime(session, bot).update_scheduled_message(
            actor_user_id=identity.user_id,
            group_id=group_id,
            entry_id=entry_id,
            text=text,
            schedule=schedule,
            delete_after_seconds=delete_after_seconds,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return {"status": "ok", "scheduled_message": entry}


@router.post("/api/admin/groups/{group_id}/scheduled-messages/{entry_id}/send-now")
@router.post("/webapp/groups/{group_id}/scheduled-messages/{entry_id}/send-now")
async def webapp_send_scheduled_message_now(
    group_id: int,
    entry_id: str,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
    bot: Bot = Depends(get_bot),
) -> dict[str, object]:
    await ensure_group_admin(group_id, session, identity)
    try:
        result = await _runtime(session, bot).send_scheduled_message_now(
            group_id=group_id,
            entry_id=entry_id,
            bot=bot,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return {"status": "ok", "result": result}

@router.delete("/api/admin/groups/{group_id}/scheduled-messages/{entry_id}")
@router.delete("/webapp/groups/{group_id}/scheduled-messages/{entry_id}")
async def webapp_delete_scheduled_message(
    group_id: int,
    entry_id: str,
    identity: TelegramWebAppIdentity = Depends(get_identity),
    session: AsyncSession = Depends(get_session),
    bot: Bot = Depends(get_bot),
) -> dict[str, object]:
    await ensure_group_admin(group_id, session, identity)
    deleted = await _runtime(session, bot).delete_scheduled_message(actor_user_id=identity.user_id, group_id=group_id, entry_id=entry_id)
    return {"status": "ok" if deleted else "missing", "deleted": deleted}


__all__ = ["router"]
