from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.event_bus import Event, EventBus
from bot.db.models import Agent
from bot.services.permission_service import PermissionService


class AgentServiceSupport:
    def __init__(self, session: AsyncSession, event_bus: EventBus | None = None) -> None:
        self.session = session
        self.event_bus = event_bus

    async def ensure_group_admin(self, group_id: int, actor_user_id: int) -> None:
        from bot.config import get_settings
        if actor_user_id in get_settings().bot_owner_ids:
            return
        can_manage = await PermissionService(self.session).can(group_id, actor_user_id, "group.settings.update")
        if not can_manage:
            raise PermissionError("User does not have permission to manage agents for this group")

    async def ensure_agent_owner(self, agent: Agent, actor_user_id: int) -> None:
        from bot.config import get_settings
        if actor_user_id in get_settings().bot_owner_ids:
            return
        if agent.linked_by_user_id is not None and int(agent.linked_by_user_id) != int(actor_user_id):
            raise PermissionError("You do not own this agent")

    async def publish(self, name: str, *, group_id: int, user_id: int, payload: dict[str, Any]) -> None:
        if self.event_bus is None:
            return
        await self.event_bus.publish(Event(name=name, group_id=group_id, user_id=user_id, payload=payload))

    async def get_agent(self, *, agent_id: int) -> Agent | None:
        return (await self.session.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
