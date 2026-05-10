"""Queue helpers for agent jobs without importing the agent worker actor."""

from __future__ import annotations

from dramatiq.message import Message
from redis.exceptions import RedisError
import structlog
from sqlalchemy import select

from bot.db.models import AgentJob
from bot.db.session import SessionLocal
from bot.workers.app import redis_broker


logger = structlog.get_logger(__name__)


async def dispatch_agent_job(job_id: int) -> None:
    async with SessionLocal() as session:
        job = (await session.execute(select(AgentJob).where(AgentJob.id == job_id))).scalar_one_or_none()
        if job is None:
            logger.bind(job_id=job_id).warning("agent_job_missing_for_dispatch")
            return
        try:
            redis_broker.enqueue(
                Message(
                    queue_name="agent",
                    actor_name="execute_agent_job",
                    args=(job.agent_id, job.id),
                    kwargs={},
                    options={},
                )
            )
        except RedisError as exc:
            logger.bind(job_id=job.id, agent_id=job.agent_id, error=str(exc)).warning("agent_job_enqueue_failed")

