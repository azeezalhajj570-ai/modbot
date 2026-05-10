from __future__ import annotations

from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.agents.contracts import AgentJobOwnership
from bot.agents.jobs import GROUP_MEMBER_BROADCAST_JOB_TYPE, normalize_group_member_broadcast_payload
from bot.core.event_bus import EventBus
from bot.db.models import Agent, AgentJob

from .agent_notification_service import AgentNotificationService
from .service_support import AgentServiceSupport


def _job_queued_notification(job_type: str, payload: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    if job_type == GROUP_MEMBER_BROADCAST_JOB_TYPE:
        group_title = str(payload.get("source_group_title") or "").strip()
        selected_count = len(list(payload.get("selected_user_ids") or []))
        summary = f"Queued for {group_title}." if group_title else "Queued for the selected source group."
        notification_payload = {
            "job_type": job_type,
            "source_group_title": group_title,
            "selected_count": selected_count,
            "job_payload": dict(payload),
        }
        return "Bulk message queued", summary, notification_payload

    return (
        "Job queued",
        f"{job_type.replace('_', ' ')} queued for this agent.",
        {"job_type": job_type, "job_payload": dict(payload)},
    )


class AgentJobService(AgentServiceSupport):
    def __init__(self, session: AsyncSession, event_bus: EventBus | None = None) -> None:
        super().__init__(session, event_bus)

    async def create_job(
        self,
        *,
        actor_user_id: int,
        agent_id: int,
        job_type: str,
        job_payload: dict[str, Any] | None = None,
    ) -> AgentJob:
        agent = await self.get_agent(agent_id=agent_id)
        if agent is None:
            raise ValueError("Agent not found")
        await self.ensure_agent_owner(agent, actor_user_id)
        if agent.auth_state != "active":
            raise ValueError("Agent is not authenticated")
        normalized_job_type = job_type.strip()
        if not normalized_job_type:
            raise ValueError("Job type is required")
        normalized_payload = dict(job_payload or {})
        if normalized_job_type == GROUP_MEMBER_BROADCAST_JOB_TYPE:
            normalized_payload = normalize_group_member_broadcast_payload(normalized_payload)
            await self._validate_broadcast_preflight(agent, normalized_payload)

        job = AgentJob(agent_id=agent.id, job_type=normalized_job_type, job_payload=normalized_payload, status="pending")
        self.session.add(job)
        await self.session.commit()
        notification_title, notification_body, notification_payload = _job_queued_notification(
            normalized_job_type,
            normalized_payload,
        )
        await AgentNotificationService(self.session).create_notification(
            actor_user_id=actor_user_id,
            agent=agent,
            kind="job_queued",
            title=notification_title,
            body=notification_body,
            payload={"job_id": job.id, **notification_payload},
        )
        await self.publish(
            "agent_job_created",
            group_id=agent.group_id,
            user_id=actor_user_id,
            payload={"agent_id": agent.id, "job_id": job.id, "job_type": normalized_job_type},
        )
        return job

    async def list_jobs(self, *, actor_user_id: int, group_id: int, limit: int = 20) -> list[AgentJob]:
        await self.ensure_group_admin(group_id, actor_user_id)
        stmt = (
            select(AgentJob)
            .join(Agent, Agent.id == AgentJob.agent_id)
            .where(Agent.group_id == group_id)
            .order_by(desc(AgentJob.created_at), desc(AgentJob.id))
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def list_agent_jobs(self, *, actor_user_id: int, agent_id: int, limit: int = 20) -> list[AgentJob]:
        agent = await self.get_agent(agent_id=agent_id)
        if agent is None:
            return []
        await self.ensure_agent_owner(agent, actor_user_id)
        stmt = (
            select(AgentJob)
            .where(AgentJob.agent_id == agent.id)
            .order_by(desc(AgentJob.created_at), desc(AgentJob.id))
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def queue_automation_task_job(
        self,
        *,
        group_id: int,
        agent_id: int,
        task_key: str,
        assignment_id: str,
        task_config: dict[str, Any],
        conditions: dict[str, Any],
        event: dict[str, Any],
    ) -> AgentJobOwnership:
        agent = await self.get_agent(agent_id=agent_id)
        if agent is None:
            raise ValueError("Assigned agent is not available")
        if agent.group_id != group_id or agent.auth_state != "active":
            raise ValueError("Assigned agent is not available")

        job = AgentJob(
            agent_id=agent.id,
            job_type="automation_task",
            job_payload={
                "task_key": task_key,
                "task_config": dict(task_config),
                "conditions": dict(conditions),
                "assignment_id": assignment_id,
                "event": dict(event),
            },
            status="pending",
        )
        self.session.add(job)
        await self.session.commit()
        await self.publish(
            "agent_job_created",
            group_id=group_id,
            user_id=None,
            payload={"agent_id": agent.id, "job_id": job.id, "job_type": job.job_type},
        )
        return AgentJobOwnership(
            job_id=job.id,
            agent_id=agent.id,
            group_id=group_id,
            job_type=job.job_type,
            status=job.status,
        )

    async def update_job_status(self, *, actor_user_id: int, job_id: int, status: str) -> AgentJob:
        job = (await self.session.execute(select(AgentJob).where(AgentJob.id == job_id))).scalar_one_or_none()
        if job is None:
            raise ValueError("Job not found")
        agent = await self.get_agent(agent_id=job.agent_id)
        if agent is None:
            raise ValueError("Agent not found")
        await self.ensure_agent_owner(agent, actor_user_id)
        job.status = status.strip() or job.status
        await self.session.commit()
        return job

    async def delete_job(self, *, actor_user_id: int, job_id: int) -> bool:
        job = (await self.session.execute(select(AgentJob).where(AgentJob.id == job_id))).scalar_one_or_none()
        if job is None:
            return False
        agent = await self.get_agent(agent_id=job.agent_id)
        if agent is None:
            return False
        await self.ensure_agent_owner(agent, actor_user_id)
        await self.session.delete(job)
        await self.session.commit()
        return True

    async def _validate_broadcast_preflight(self, agent: Agent, payload: dict[str, Any]) -> None:
        from bot.config import get_settings
        from bot.utils.rate_limiter import AgentRateLimiter
        from redis.asyncio import Redis

        redis_client = Redis.from_url(get_settings().redis_url, decode_responses=True)
        try:
            limiter = AgentRateLimiter(redis_client)

            cooldown_mins = getattr(agent, "cooldown_minutes", None)
            if cooldown_mins is not None and cooldown_mins > 0:
                in_cooldown, remaining = await limiter.is_in_cooldown(agent.id, cooldown_mins)
                if in_cooldown:
                    raise ValueError(f"Agent is in cooldown for {int(remaining)} more seconds")

            safety_enabled = getattr(agent, "safety_mode_enabled", True)
            safety_until = getattr(agent, "safety_mode_until", None)
            if await limiter.check_safety_mode(agent.id, safety_enabled, safety_until):
                raise ValueError("Agent is in safety mode and cannot send bulk messages")

            max_per_hour = getattr(agent, "max_actions_per_hour", None)
            if max_per_hour is not None and max_per_hour > 0:
                allowed, count = await limiter.check_and_increment(agent.id, max_per_hour)
                if not allowed:
                    raise ValueError(f"Hourly rate limit reached ({count}/{max_per_hour}). Try again later.")

            max_per_day = getattr(agent, "max_messages_per_day", None) or 500
            if max_per_day > 0:
                allowed, count = await limiter.check_daily_limit(agent.id, max_per_day)
                if not allowed:
                    raise ValueError(f"Daily message limit reached ({count}/{max_per_day}). Try again tomorrow.")

            threshold = int(payload.get("threshold") or 0)
            if threshold > max_per_day:
                raise ValueError(f"Threshold ({threshold}) exceeds daily limit ({max_per_day})")
            if threshold > 500:
                raise ValueError(f"Maximum batch size is 500. Requested: {threshold}")

            selected = list(payload.get("selected_user_ids") or [])
            if len(selected) > threshold:
                raise ValueError(f"Selected members ({len(selected)}) exceeds threshold ({threshold})")

        finally:
            await redis_client.aclose()
