from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.agents.contracts import LinkedAccountIdentity
from bot.core.event_bus import EventBus
from bot.db.models import Agent, Group, GroupAdminRole
from bot.services.group_service import GroupService, upsert_group

from .phone import normalize_optional_agent_phone_number
from .service_support import AgentServiceSupport

AGENTS_WORKSPACE_TG_GROUP_BASE = -8_000_000_000_000_000


class LinkedAccountService(AgentServiceSupport):
    def __init__(self, session: AsyncSession, event_bus: EventBus | None = None) -> None:
        super().__init__(session, event_bus)

    async def create_agent(
        self,
        *,
        actor_user_id: int,
        group_id: int | None,
        external_account_id: str | None = None,
        phone_number: str | None = None,
        telegram_user_id: int | None = None,
        metadata: dict | None = None,
    ) -> Agent:
        normalized_account_id = str(external_account_id or "").strip()
        if not normalized_account_id:
            raise ValueError("Agent account identifier is required")
        normalized_phone_number = normalize_optional_agent_phone_number(phone_number)

        existing = (
            await self.session.execute(
                select(Agent).where(
                    Agent.linked_by_user_id == actor_user_id,
                    Agent.external_account_id == normalized_account_id,
                )
            )
        ).scalars().first()
        if existing:
            if existing.auth_state in {"pending_auth", "pending_code", "pending_2fa", "failed"}:
                existing.phone_number = normalized_phone_number or existing.phone_number
                existing.auth_state = "pending_auth"
                existing.status = "pending"
                await self.session.commit()
                return existing
            raise ValueError("Agent account is already linked")
        if normalized_phone_number:
            existing_phone = (
                await self.session.execute(
                    select(Agent).where(
                        Agent.phone_number == normalized_phone_number,
                        Agent.linked_by_user_id == actor_user_id,
                    )
                )
            ).scalars().first()
            if existing_phone:
                raise ValueError("Phone number is already linked for this subscription")

        agent = Agent(
            telegram_user_id=telegram_user_id,
            linked_by_user_id=actor_user_id,
            group_id=group_id,
            phone_number=normalized_phone_number,
            external_account_id=normalized_account_id,
            status="pending",
            auth_state="pending_auth",
            details=dict(metadata or {}),
        )
        self.session.add(agent)
        await self.session.commit()
        await self.publish(
            "agent_linked",
            group_id=group_id or 0,
            user_id=actor_user_id,
            payload={"agent_id": agent.id, "external_account_id": normalized_account_id},
        )
        return agent

    async def update_agent(
        self,
        *,
        actor_user_id: int,
        agent_id: int,
        external_account_id: str | None = None,
        phone_number: str | None = None,
        telegram_user_id: int | None = None,
        metadata: dict | None = None,
    ) -> Agent:
        agent = await self.get_agent(agent_id=agent_id)
        if agent is None:
            raise ValueError("Agent not found")
        await self.ensure_agent_owner(agent, actor_user_id)

        normalized_account_id = str(external_account_id or "").strip()
        if not normalized_account_id:
            raise ValueError("Agent account identifier is required")
        normalized_phone_number = normalize_optional_agent_phone_number(phone_number)

        existing = (
            await self.session.execute(
                select(Agent).where(
                    Agent.group_id == agent.group_id,
                    Agent.external_account_id == normalized_account_id,
                    Agent.id != agent.id,
                )
            )
        ).scalars().first()
        if existing:
            raise ValueError("Agent account is already linked for this group")
        if normalized_phone_number:
            existing_phone = (
                await self.session.execute(
                    select(Agent).where(
                        Agent.phone_number == normalized_phone_number,
                        Agent.id != agent.id,
                        or_(Agent.group_id == agent.group_id, Agent.linked_by_user_id == actor_user_id),
                    )
                )
            ).scalars().first()
            if existing_phone:
                raise ValueError("Phone number is already linked for this subscription")

        agent.external_account_id = normalized_account_id
        agent.phone_number = normalized_phone_number
        agent.telegram_user_id = telegram_user_id
        agent.linked_by_user_id = agent.linked_by_user_id or actor_user_id
        agent.details = dict(metadata or {})
        await self.session.commit()
        await self.publish(
            "agent_updated",
            group_id=agent.group_id,
            user_id=actor_user_id,
            payload={"agent_id": agent.id, "external_account_id": normalized_account_id},
        )
        return agent

    async def unlink_agent(self, *, actor_user_id: int, agent_id: int) -> bool:
        agent = await self.get_agent(agent_id=agent_id)
        if agent is None:
            return False
        await self.ensure_agent_owner(agent, actor_user_id)
        group_id = agent.group_id
        external_account_id = agent.external_account_id
        await self.session.delete(agent)
        await self.session.commit()
        await self.publish(
            "agent_unlinked",
            group_id=group_id,
            user_id=actor_user_id,
            payload={"agent_id": agent_id, "external_account_id": external_account_id},
        )
        return True

    async def list_agents(self, *, actor_user_id: int, group_id: int | None = None) -> list[Agent]:
        from bot.config import get_settings
        if actor_user_id not in get_settings().bot_owner_ids:
            return list(
                (
                    await self.session.execute(
                        select(Agent).where(Agent.linked_by_user_id == actor_user_id).order_by(Agent.created_at.desc(), Agent.id.desc())
                    )
                ).scalars()
            )
        stmt = select(Agent).order_by(Agent.created_at.desc(), Agent.id.desc())
        if group_id is not None:
            from sqlalchemy import or_
            stmt = stmt.where(or_(Agent.group_id == group_id, Agent.group_id.is_(None)))
        return list((await self.session.execute(stmt)).scalars())

    async def list_all_active_agents(self, *, actor_user_id: int) -> list[Agent]:
        admin_groups = await GroupService(self.session).list_admin_groups_all(actor_user_id)
        agents: list[Agent] = []
        for group in admin_groups:
            agents.extend(
                [
                    agent
                    for agent in await self.list_agents(actor_user_id=actor_user_id, group_id=int(group["id"]))
                    if agent.auth_state == "active"
                ]
            )
        return agents

    async def get_agent_by_external_account(
        self,
        *,
        actor_user_id: int,
        group_id: int,
        external_account_id: str,
    ) -> Agent | None:
        await self.ensure_group_admin(group_id, actor_user_id)
        normalized_account_id = external_account_id.strip()
        if not normalized_account_id:
            return None
        return (
            await self.session.execute(
                select(Agent).where(
                    Agent.group_id == group_id,
                    Agent.external_account_id == normalized_account_id,
                )
            )
        ).scalar_one_or_none()

    async def describe_linked_account(self, *, agent_id: int) -> LinkedAccountIdentity | None:
        agent = await self.get_agent(agent_id=agent_id)
        if agent is None:
            return None
        return self._to_identity(agent)

    async def list_linked_account_identities(self, *, actor_user_id: int, group_id: int) -> list[LinkedAccountIdentity]:
        agents = await self.list_agents(actor_user_id=actor_user_id, group_id=group_id)
        return [self._to_identity(agent) for agent in agents]

    async def ensure_agents_workspace_group(self, *, actor_user_id: int) -> int:
        workspace_tg_group_id = AGENTS_WORKSPACE_TG_GROUP_BASE - actor_user_id
        group = await upsert_group(
            self.session,
            tg_group_id=workspace_tg_group_id,
            title="Agents Workspace",
            is_active=False,
        )

        role = (
            await self.session.execute(
                select(GroupAdminRole).where(
                    GroupAdminRole.group_id == group.id,
                    GroupAdminRole.user_id == actor_user_id,
                )
            )
        ).scalar_one_or_none()
        if role is None:
            self.session.add(GroupAdminRole(group_id=group.id, user_id=actor_user_id, role="owner"))
            await self.session.commit()
        return group.id

    @staticmethod
    def _to_identity(agent: Agent) -> LinkedAccountIdentity:
        return LinkedAccountIdentity(
            agent_id=agent.id,
            group_id=agent.group_id,
            external_account_id=str(agent.external_account_id or ""),
            telegram_user_id=agent.telegram_user_id,
        )
