"""Agent management facade over focused agent-domain services."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from bot.agents.contracts import AccountGroupVisibility, AccountSessionState, AgentJobOwnership, LinkedAccountIdentity
from bot.agents.account_group_membership_service import AccountGroupMembershipService
from bot.agents.account_session_service import AccountSessionService
from bot.agents.agent_job_service import AgentJobService
from bot.agents.auth import AgentTelegramAuthResult, AgentTelegramAuthService
from bot.agents.linked_account_service import LinkedAccountService
from bot.agents.service_errors import AgentAuthStateError
from bot.core.event_bus import EventBus
from bot.db.models import Agent, AgentJob


__all__ = ["AgentAuthStateError", "AgentService"]


class AgentService:
    def __init__(self, session: AsyncSession, event_bus: EventBus | None = None) -> None:
        self.session = session
        self.event_bus = event_bus
        self.linked_accounts = LinkedAccountService(session, event_bus)
        self.account_sessions = AccountSessionService(session, event_bus)
        self.memberships = AccountGroupMembershipService(session)
        self.jobs = AgentJobService(session, event_bus)

    async def create_agent(
        self,
        *,
        actor_user_id: int,
        group_id: int,
        external_account_id: str,
        telegram_user_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Agent:
        return await self.linked_accounts.create_agent(
            actor_user_id=actor_user_id,
            group_id=group_id,
            external_account_id=external_account_id,
            telegram_user_id=telegram_user_id,
            metadata=metadata,
        )

    async def start_agent_login(
        self,
        *,
        actor_user_id: int,
        group_id: int,
        phone_number: str,
        agent_id: int | None = None,
        auth_service: AgentTelegramAuthService | None = None,
    ) -> Agent:
        return await self.account_sessions.start_agent_login(
            actor_user_id=actor_user_id,
            group_id=group_id,
            phone_number=phone_number,
            agent_id=agent_id,
            auth_service=auth_service,
        )

    async def complete_agent_code(
        self,
        *,
        actor_user_id: int,
        agent_id: int,
        code: str,
        auth_service: AgentTelegramAuthService | None = None,
    ) -> Agent:
        return await self.account_sessions.complete_agent_code(
            actor_user_id=actor_user_id,
            agent_id=agent_id,
            code=code,
            auth_service=auth_service,
        )

    async def complete_agent_password(
        self,
        *,
        actor_user_id: int,
        agent_id: int,
        password: str,
        auth_service: AgentTelegramAuthService | None = None,
    ) -> Agent:
        return await self.account_sessions.complete_agent_password(
            actor_user_id=actor_user_id,
            agent_id=agent_id,
            password=password,
            auth_service=auth_service,
        )

    async def _finalize_agent_auth(
        self,
        *,
        agent: Agent,
        result: AgentTelegramAuthResult,
        actor_user_id: int,
    ) -> None:
        await self.account_sessions._finalize_agent_auth(agent=agent, result=result, actor_user_id=actor_user_id)

    async def update_agent(
        self,
        *,
        actor_user_id: int,
        agent_id: int,
        external_account_id: str,
        telegram_user_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Agent:
        return await self.linked_accounts.update_agent(
            actor_user_id=actor_user_id,
            agent_id=agent_id,
            external_account_id=external_account_id,
            telegram_user_id=telegram_user_id,
            metadata=metadata,
        )

    async def unlink_agent(self, *, actor_user_id: int, agent_id: int) -> bool:
        return await self.linked_accounts.unlink_agent(actor_user_id=actor_user_id, agent_id=agent_id)

    async def list_agents(self, *, actor_user_id: int, group_id: int) -> list[Agent]:
        return await self.linked_accounts.list_agents(actor_user_id=actor_user_id, group_id=group_id)

    async def list_all_active_agents(self, *, actor_user_id: int) -> list[Agent]:
        return await self.linked_accounts.list_all_active_agents(actor_user_id=actor_user_id)

    async def list_managed_member_groups(self, *, actor_user_id: int, agent_id: int) -> list[dict[str, Any]]:
        return await self.memberships.list_managed_member_groups(actor_user_id=actor_user_id, agent_id=agent_id)

    async def search_agent_member_group_members(
        self,
        *,
        actor_user_id: int,
        agent_id: int,
        tg_group_id: int,
        query: str | None = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        return await self.memberships.search_agent_member_group_members(
            actor_user_id=actor_user_id,
            agent_id=agent_id,
            tg_group_id=tg_group_id,
            query=query,
            limit=limit,
        )

    async def search_group_members(
        self,
        *,
        actor_user_id: int,
        group_id: int,
        query: str | None = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        return await self.memberships.search_group_members(
            actor_user_id=actor_user_id,
            group_id=group_id,
            query=query,
            limit=limit,
        )

    async def list_persisted_group_members(
        self,
        *,
        actor_user_id: int,
        group_id: int,
        query: str | None = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        await self.linked_accounts.ensure_group_admin(group_id, actor_user_id)
        return await self.memberships._list_persisted_group_members(
            group_id=group_id,
            query=query,
            limit=limit,
        )

    async def get_agent(self, *, agent_id: int) -> Agent | None:
        return await self.linked_accounts.get_agent(agent_id=agent_id)

    async def get_agent_by_external_account(
        self,
        *,
        actor_user_id: int,
        group_id: int,
        external_account_id: str,
    ) -> Agent | None:
        return await self.linked_accounts.get_agent_by_external_account(
            actor_user_id=actor_user_id,
            group_id=group_id,
            external_account_id=external_account_id,
        )

    async def create_job(
        self,
        *,
        actor_user_id: int,
        agent_id: int,
        job_type: str,
        job_payload: dict[str, Any] | None = None,
    ) -> AgentJob:
        return await self.jobs.create_job(
            actor_user_id=actor_user_id,
            agent_id=agent_id,
            job_type=job_type,
            job_payload=job_payload,
        )

    async def list_jobs(self, *, actor_user_id: int, group_id: int, limit: int = 20) -> list[AgentJob]:
        return await self.jobs.list_jobs(actor_user_id=actor_user_id, group_id=group_id, limit=limit)

    async def list_agent_jobs(self, *, actor_user_id: int, agent_id: int, limit: int = 20) -> list[AgentJob]:
        return await self.jobs.list_agent_jobs(actor_user_id=actor_user_id, agent_id=agent_id, limit=limit)

    async def update_job_status(self, *, actor_user_id: int, job_id: int, status: str) -> AgentJob:
        return await self.jobs.update_job_status(actor_user_id=actor_user_id, job_id=job_id, status=status)

    async def delete_job(self, *, actor_user_id: int, job_id: int) -> bool:
        return await self.jobs.delete_job(actor_user_id=actor_user_id, job_id=job_id)

    async def describe_linked_account(self, *, agent_id: int) -> LinkedAccountIdentity | None:
        return await self.linked_accounts.describe_linked_account(agent_id=agent_id)

    async def get_account_session_state(self, *, agent_id: int) -> AccountSessionState | None:
        return await self.account_sessions.get_account_session_state(agent_id=agent_id)

    async def list_account_group_visibility(self, *, actor_user_id: int, agent_id: int) -> list[AccountGroupVisibility]:
        return await self.memberships.list_account_group_visibility(actor_user_id=actor_user_id, agent_id=agent_id)

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
        return await self.jobs.queue_automation_task_job(
            group_id=group_id,
            agent_id=agent_id,
            task_key=task_key,
            assignment_id=assignment_id,
            task_config=task_config,
            conditions=conditions,
            event=event,
        )
