"""Dramatiq tasks for Telegram group membership actions."""

from __future__ import annotations

import asyncio
from typing import Final

import dramatiq
from dramatiq import Retry
import structlog
from sqlalchemy import desc, select

from bot.agents.exceptions import AgentBannedError, AgentFloodWaitError, AgentSessionError
from bot.agents.group_membership import (
    ERROR_FLOOD_WAIT,
    ERROR_UNKNOWN,
    ERROR_USER_ALREADY_IN_GROUP,
    AddUserResult,
    add_user_to_group,
)
from bot.agents.session import SessionManager
from bot.db.models import Agent, AgentJob, Group, GroupMember, MembershipAuditLog
from bot.db.session import SessionLocal
from bot.workers.app import redis_broker  # noqa: F401


QUEUE_NAME: Final = "membership"
ACTION_ADD: Final = "add"
RESULT_SUCCESS: Final = "success"
SOURCE_MEMBERSHIP_ADD: Final = "membership_add"

logger = structlog.get_logger(__name__)


async def _update_agent_job(
    *,
    agent_job_id: int | None,
    status: str,
    result: dict | None = None,
    error: str | None = None,
) -> None:
    if agent_job_id is None:
        return
    from bot.db.session import SessionLocal
    async with SessionLocal() as session:
        job = (await session.execute(select(AgentJob).where(AgentJob.id == agent_job_id))).scalar_one_or_none()
        if job is None:
            return
        payload = dict(job.job_payload or {})
        if result is not None:
            payload["result"] = result
        if error is not None:
            payload["last_error"] = error
        job.job_payload = payload
        job.status = status
        await session.commit()


async def _load_runnable_agent_job(agent_job_id: int | None) -> AgentJob | None:
    if agent_job_id is None:
        return None
    from bot.db.session import SessionLocal
    async with SessionLocal() as session:
        job = (await session.execute(select(AgentJob).where(AgentJob.id == agent_job_id))).scalar_one_or_none()
        if job is None:
            return None
        if job.status in {"aborted", "completed"}:
            return None
        return job


async def _write_membership_audit(
    *,
    group_id: int,
    user_id: int,
    requested_by: int,
    result: str,
    flood_wait_seconds: int | None = None,
) -> None:
    from bot.db.session import SessionLocal
    async with SessionLocal() as session:
        session.add(
            MembershipAuditLog(
                group_id=group_id,
                user_id=user_id,
                requested_by=requested_by,
                action=ACTION_ADD,
                result=result,
                flood_wait_sec=flood_wait_seconds,
            )
        )
        await session.commit()


async def _mark_group_member_added(*, group_id: int, user_id: int) -> None:
    from bot.db.session import SessionLocal
    async with SessionLocal() as session:
        existing = (
            await session.execute(
                select(GroupMember).where(
                    GroupMember.group_id == group_id,
                    GroupMember.tg_user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                GroupMember(
                    group_id=group_id,
                    tg_user_id=user_id,
                    role="member",
                    source=SOURCE_MEMBERSHIP_ADD,
                )
            )
        else:
            existing.source = SOURCE_MEMBERSHIP_ADD
        await session.commit()


async def _run_add_user_to_group_task(group_id: int, user_id: int, requested_by: int) -> None:
    bound_logger = logger.bind(group_id=group_id, user_id=user_id, requested_by=requested_by)
    bound_logger.info("membership_add_task_started")

    from bot.db.session import SessionLocal
    async with SessionLocal() as session:
        group = (await session.execute(select(Group).where(Group.id == group_id))).scalar_one_or_none()
        if group is None:
            bound_logger.warning("membership_add_group_missing")
            return

        existing_member = (
            await session.execute(
                select(GroupMember).where(
                    GroupMember.group_id == group_id,
                    GroupMember.tg_user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if existing_member is not None:
            result = AddUserResult(success=False, error_code=ERROR_USER_ALREADY_IN_GROUP)
        else:
            agent = (
                await session.execute(
                    select(Agent)
                    .where(
                        Agent.group_id == group_id,
                        Agent.auth_state == "active",
                        Agent.session_string.is_not(None),
                    )
                    .order_by(desc(Agent.updated_at), desc(Agent.id))
                )
            ).scalar_one_or_none()
            if agent is None:
                result = AddUserResult(success=False, error_code=ERROR_UNKNOWN)
            else:
                try:
                    client = await SessionManager(session_factory=SessionLocal).get_client(agent.id)
                    try:
                        result = await add_user_to_group(client, group.tg_group_id, user_id)
                    finally:
                        await client.disconnect()
                except AgentFloodWaitError as exc:
                    result = AddUserResult(
                        success=False,
                        error_code=ERROR_FLOOD_WAIT,
                        flood_wait_seconds=exc.retry_after,
                    )
                except (AgentSessionError, AgentBannedError):
                    result = AddUserResult(success=False, error_code=ERROR_UNKNOWN)

    result_name = RESULT_SUCCESS if result.success else str(result.error_code or ERROR_UNKNOWN)
    await _write_membership_audit(
        group_id=group_id,
        user_id=user_id,
        requested_by=requested_by,
        result=result_name,
        flood_wait_seconds=result.flood_wait_seconds,
    )

    if result.error_code == ERROR_FLOOD_WAIT:
        bound_logger.warning(
            "membership_add_task_retrying",
            error_code=result.error_code,
            flood_wait_seconds=result.flood_wait_seconds,
        )
        raise Retry(
            message="Telegram flood wait while adding user to group",
            delay=(int(result.flood_wait_seconds or 0) * 1000) + 1000,
        )

    if result.success:
        await _mark_group_member_added(group_id=group_id, user_id=user_id)
        bound_logger.info("membership_add_task_succeeded", error_code=None, flood_wait_seconds=None)
        return

    bound_logger.warning(
        "membership_add_task_finished",
        error_code=result.error_code,
        flood_wait_seconds=result.flood_wait_seconds,
    )


@dramatiq.actor(queue_name=QUEUE_NAME, max_retries=3, min_backoff=5000)
def add_user_to_group_task(
    group_id: int,
    user_id: int,
    requested_by: int,
    agent_id: int | None = None,
    target_tg_group_id: int | None = None,
    agent_job_id: int | None = None,
) -> None:
    asyncio.run(_run_add_user_to_group_task_with_agent(group_id, user_id, requested_by, agent_id, target_tg_group_id, agent_job_id))


async def _run_add_user_to_group_task_with_agent(
    group_id: int,
    user_id: int,
    requested_by: int,
    agent_id: int | None = None,
    target_tg_group_id: int | None = None,
    agent_job_id: int | None = None,
) -> None:
    bound_logger = logger.bind(
        group_id=group_id,
        user_id=user_id,
        requested_by=requested_by,
        agent_id=agent_id,
        target_tg_group_id=target_tg_group_id,
        agent_job_id=agent_job_id,
    )
    bound_logger.info("membership_add_task_started")
    existing_job = await _load_runnable_agent_job(agent_job_id)
    if agent_job_id is not None and existing_job is None:
        bound_logger.info("membership_add_task_skipped", reason="job_not_runnable")
        return
    await _update_agent_job(agent_job_id=agent_job_id, status="running")

    from bot.db.session import SessionLocal
    async with SessionLocal() as session:
        group = (await session.execute(select(Group).where(Group.id == group_id))).scalar_one_or_none()
        if group is None:
            bound_logger.warning("membership_add_group_missing")
            await _update_agent_job(agent_job_id=agent_job_id, status="failed", error="Target group not found")
            return

        existing_member = (
            await session.execute(
                select(GroupMember).where(
                    GroupMember.group_id == group_id,
                    GroupMember.tg_user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if existing_member is not None:
            result = AddUserResult(success=False, error_code=ERROR_USER_ALREADY_IN_GROUP)
        else:
            agent_query = select(Agent).where(
                Agent.auth_state == "active",
                Agent.session_string.is_not(None),
            )
            if agent_id is not None:
                agent_query = agent_query.where(Agent.id == agent_id)
            else:
                agent_query = agent_query.where(Agent.group_id == group_id).order_by(desc(Agent.updated_at), desc(Agent.id))
            agent = (await session.execute(agent_query)).scalars().first()
            if agent is None:
                result = AddUserResult(success=False, error_code=ERROR_UNKNOWN)
            else:
                effective_tg_group_id = int(target_tg_group_id or group.tg_group_id)
                try:
                    client = await SessionManager(session_factory=SessionLocal).get_client(agent.id)
                    try:
                        result = await add_user_to_group(client, effective_tg_group_id, user_id)
                    finally:
                        await client.disconnect()
                except AgentFloodWaitError as exc:
                    result = AddUserResult(
                        success=False,
                        error_code=ERROR_FLOOD_WAIT,
                        flood_wait_seconds=exc.retry_after,
                    )
                except (AgentSessionError, AgentBannedError):
                    result = AddUserResult(success=False, error_code=ERROR_UNKNOWN)

    result_name = RESULT_SUCCESS if result.success else str(result.error_code or ERROR_UNKNOWN)
    await _write_membership_audit(
        group_id=group_id,
        user_id=user_id,
        requested_by=requested_by,
        result=result_name,
        flood_wait_seconds=result.flood_wait_seconds,
    )

    if result.error_code == ERROR_FLOOD_WAIT:
        await _update_agent_job(
            agent_job_id=agent_job_id,
            status="queued",
            error=f"flood_wait:{int(result.flood_wait_seconds or 0)}",
        )
        bound_logger.warning(
            "membership_add_task_retrying",
            error_code=result.error_code,
            flood_wait_seconds=result.flood_wait_seconds,
        )
        raise Retry(
            message="Telegram flood wait while adding user to group",
            delay=(int(result.flood_wait_seconds or 0) * 1000) + 1000,
        )

    if result.success:
        await _mark_group_member_added(group_id=group_id, user_id=user_id)
        await _update_agent_job(
            agent_job_id=agent_job_id,
            status="completed",
            result={"user_id": user_id, "target_tg_group_id": int(target_tg_group_id or group.tg_group_id)},
        )
        bound_logger.info("membership_add_task_succeeded", error_code=None, flood_wait_seconds=None)
        return

    if result.error_code == ERROR_USER_ALREADY_IN_GROUP:
        await _update_agent_job(
            agent_job_id=agent_job_id,
            status="completed",
            result={"user_id": user_id, "target_tg_group_id": int(target_tg_group_id or group.tg_group_id), "skipped": "already_member"},
        )
    else:
        await _update_agent_job(
            agent_job_id=agent_job_id,
            status="failed",
            error=str(result.error_code or ERROR_UNKNOWN),
        )
    bound_logger.warning(
        "membership_add_task_finished",
        error_code=result.error_code,
        flood_wait_seconds=result.flood_wait_seconds,
    )
