from __future__ import annotations

from typing import Any

from sqlalchemy import desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Agent, AgentNotification

from .service_support import AgentServiceSupport


class AgentNotificationService(AgentServiceSupport):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def create_notification(
        self,
        *,
        actor_user_id: int | None,
        agent: Agent | None = None,
        group_id: int | None = None,
        kind: str,
        title: str,
        body: str,
        payload: dict[str, Any] | None = None,
    ) -> AgentNotification:
        resolved_group_id = agent.group_id if (agent and agent.group_id is not None) else group_id
        if resolved_group_id is None:
            resolved_group_id = 0

        if actor_user_id is not None and agent is None and resolved_group_id > 0:
            await self.ensure_group_admin(resolved_group_id, actor_user_id)

        notification = AgentNotification(
            agent_id=agent.id if agent else None,
            group_id=resolved_group_id,
            kind=kind.strip() or "info",
            title=title.strip() or "Notification",
            body=body.strip() or "No details",
            payload=dict(payload or {}),
            is_seen=False,
        )
        self.session.add(notification)
        await self.session.commit()
        await self.session.refresh(notification)
        return notification

    async def list_notifications(
        self,
        *,
        actor_user_id: int,
        agent_id: int | None = None,
        group_id: int | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        if agent_id is None and group_id is None:
            return {"items": [], "unseen_count": 0}

        if agent_id is not None:
            agent = await self.get_agent(agent_id=agent_id)
            if agent is None:
                return {"items": [], "unseen_count": 0}
            await self.ensure_agent_owner(agent, actor_user_id)

        normalized_limit = max(1, min(int(limit), 100))
        stmt = select(AgentNotification)
        if agent_id is not None:
            stmt = stmt.where(AgentNotification.agent_id == agent_id)
        elif group_id is not None:
            await self.ensure_group_admin(group_id, actor_user_id)
            stmt = stmt.where(AgentNotification.group_id == group_id, AgentNotification.agent_id.is_(None))

        items = (
            await self.session.execute(
                stmt.order_by(desc(AgentNotification.created_at), desc(AgentNotification.id))
                .limit(normalized_limit)
            )
        ).scalars().all()

        unseen_stmt = select(func.count(AgentNotification.id)).where(
            AgentNotification.is_seen.is_(False),
        )
        if agent_id is not None:
            unseen_stmt = unseen_stmt.where(AgentNotification.agent_id == agent_id)
        elif group_id is not None:
            unseen_stmt = unseen_stmt.where(AgentNotification.group_id == group_id)

        unseen_count = int((await self.session.execute(unseen_stmt)).scalar_one() or 0)

        return {
            "items": [self.serialize_notification(item) for item in items],
            "unseen_count": unseen_count,
        }

    async def mark_all_seen(self, *, actor_user_id: int, agent_id: int | None = None, group_id: int | None = None) -> int:
        if agent_id is None and group_id is None:
            return 0

        if agent_id is not None:
            agent = await self.get_agent(agent_id=agent_id)
            if agent is None:
                return 0
            await self.ensure_agent_owner(agent, actor_user_id)

        stmt = update(AgentNotification).where(
            AgentNotification.is_seen.is_(False),
        )
        if agent_id is not None:
            stmt = stmt.where(AgentNotification.agent_id == agent_id)
        elif group_id is not None:
            await self.ensure_group_admin(group_id, actor_user_id)
            stmt = stmt.where(AgentNotification.group_id == group_id)

        result = await self.session.execute(stmt.values(is_seen=True))
        await self.session.commit()
        return int(result.rowcount or 0)

    @staticmethod
    def serialize_notification(notification: AgentNotification) -> dict[str, Any]:
        return {
            "id": notification.id,
            "agent_id": notification.agent_id,
            "group_id": notification.group_id,
            "kind": notification.kind,
            "title": notification.title,
            "body": notification.body,
            "payload": dict(notification.payload or {}),
            "is_seen": bool(notification.is_seen),
            "created_at": notification.created_at.isoformat() if notification.created_at else None,
        }
