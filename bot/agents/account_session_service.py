from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.agents.auth import AgentTelegramAuthError, AgentTelegramAuthResult, AgentTelegramAuthService, AgentTelegramTwoFactorRequired
from bot.agents.contracts import AccountSessionState
from bot.agents.session import SessionManager
from bot.core.event_bus import EventBus
from bot.db.models import Agent

from .phone import normalize_agent_phone_number
from .service_errors import AgentAuthStateError
from .service_support import AgentServiceSupport


class AccountSessionService(AgentServiceSupport):
    def __init__(self, session: AsyncSession, event_bus: EventBus | None = None, session_manager: SessionManager | None = None) -> None:
        super().__init__(session, event_bus)
        self.session_manager = session_manager or SessionManager()

    async def start_agent_login(
        self,
        *,
        actor_user_id: int,
        group_id: int = 0,
        phone_number: str,
        agent_id: int | None = None,
        auth_service: AgentTelegramAuthService | None = None,
    ) -> Agent:
        normalized_phone = normalize_agent_phone_number(phone_number)
        target_agent: Agent | None = None
        if agent_id is not None:
            target_agent = await self.get_agent(agent_id=agent_id)
            if target_agent is None:
                raise ValueError("Agent not found")
            await self.ensure_agent_owner(target_agent, actor_user_id)

        matching_agents = list(
            (
                await self.session.execute(
                    select(Agent)
                    .where(
                        Agent.phone_number == normalized_phone,
                        Agent.linked_by_user_id == actor_user_id,
                    )
                    .order_by(Agent.created_at.desc(), Agent.id.desc())
                )
            ).scalars()
        )
        if target_agent is not None:
            active_duplicate = next(
                (
                    agent
                    for agent in matching_agents
                    if agent.id != target_agent.id and agent.auth_state == "active" and agent.session_string
                ),
                None,
            )
            if active_duplicate is not None:
                raise ValueError("Phone number is already linked for this subscription")

        active_agent = next(
            (agent for agent in matching_agents if agent.auth_state == "active" and agent.session_string),
            None,
        )
        agent = target_agent or active_agent or (matching_agents[0] if matching_agents else None)
        if agent is not None and agent.auth_state == "active" and agent.session_string:
            return agent
        if (
            agent is not None
            and agent.auth_state == "pending_code"
            and agent.phone_code_hash
            and agent.session_string
            and agent.phone_number == normalized_phone
        ):
            return agent

        auth_service = auth_service or AgentTelegramAuthService()
        auth_session = await auth_service.start_login(phone_number=normalized_phone)
        if agent is None:
            agent = Agent(
                telegram_user_id=None,
                linked_by_user_id=actor_user_id,
                group_id=None,
                phone_number=normalized_phone,
                external_account_id=normalized_phone,
                status="pending",
                auth_state="pending_code",
                session_string=auth_session.session_string,
                phone_code_hash=auth_session.phone_code_hash,
                details={},
            )
            self.session.add(agent)
        else:
            agent.phone_number = normalized_phone
            agent.external_account_id = normalized_phone
            agent.linked_by_user_id = agent.linked_by_user_id or actor_user_id
            agent.status = "pending"
            agent.auth_state = "pending_code"
            agent.session_string = auth_session.session_string
            agent.phone_code_hash = auth_session.phone_code_hash
        await self.session.commit()
        return agent

    async def complete_agent_code(
        self,
        *,
        actor_user_id: int,
        agent_id: int,
        code: str,
        auth_service: AgentTelegramAuthService | None = None,
    ) -> Agent:
        agent = await self.get_agent(agent_id=agent_id)
        if agent is None:
            raise ValueError("Agent not found")
        await self.ensure_agent_owner(agent, actor_user_id)
        if agent.auth_state != "pending_code" or not agent.phone_number or not agent.phone_code_hash or not agent.session_string:
            raise AgentAuthStateError("Agent is not waiting for a login code")
        auth_service = auth_service or AgentTelegramAuthService()
        try:
            result = await auth_service.verify_code(
                phone_number=agent.phone_number,
                code=code.strip(),
                phone_code_hash=agent.phone_code_hash,
                session_string=agent.session_string,
            )
        except AgentTelegramTwoFactorRequired as exc:
            agent.auth_state = "pending_2fa"
            agent.status = "pending"
            if exc.session_string:
                agent.session_string = exc.session_string
            await self.session.commit()
            return agent
        except AgentTelegramAuthError:
            agent.auth_state = "failed"
            agent.status = "failed"
            await self.session.commit()
            raise

        await self._finalize_agent_auth(agent=agent, result=result, actor_user_id=actor_user_id)
        return agent

    async def complete_agent_password(
        self,
        *,
        actor_user_id: int,
        agent_id: int,
        password: str,
        auth_service: AgentTelegramAuthService | None = None,
    ) -> Agent:
        agent = await self.get_agent(agent_id=agent_id)
        if agent is None:
            raise ValueError("Agent not found")
        await self.ensure_agent_owner(agent, actor_user_id)
        if agent.auth_state != "pending_2fa" or not agent.session_string:
            raise AgentAuthStateError("Agent is not waiting for a 2FA password")
        auth_service = auth_service or AgentTelegramAuthService()
        try:
            result = await auth_service.verify_password(password=password, session_string=agent.session_string)
        except AgentTelegramAuthError:
            agent.auth_state = "failed"
            agent.status = "failed"
            await self.session.commit()
            raise

        await self._finalize_agent_auth(agent=agent, result=result, actor_user_id=actor_user_id)
        return agent

    async def is_available(self, agent_id: int) -> bool:
        return await self.session_manager.is_available(agent_id)

    async def get_account_session_state(self, *, agent_id: int) -> AccountSessionState | None:
        agent = await self.get_agent(agent_id=agent_id)
        if agent is None:
            return None
        return AccountSessionState(
            agent_id=agent.id,
            group_id=agent.group_id,
            auth_state=str(agent.auth_state or ""),
            status=str(agent.status or ""),
            phone_number=agent.phone_number,
            session_available=bool(agent.session_string),
        )

    async def _finalize_agent_auth(
        self,
        *,
        agent: Agent,
        result: AgentTelegramAuthResult,
        actor_user_id: int,
    ) -> None:
        display_id = result.username or result.phone_number or str(result.telegram_user_id)
        agent.telegram_user_id = result.telegram_user_id
        agent.phone_number = result.phone_number or agent.phone_number
        agent.external_account_id = display_id
        agent.status = "active"
        agent.auth_state = "active"
        agent.session_string = result.session_string
        agent.phone_code_hash = None
        details = dict(agent.details or {})
        details.update({"username": result.username, "full_name": result.full_name})
        agent.details = details
        await self.session.commit()
        await self.publish(
            "agent_linked",
            group_id=agent.group_id,
            user_id=actor_user_id,
            payload={"agent_id": agent.id, "external_account_id": agent.external_account_id},
        )
