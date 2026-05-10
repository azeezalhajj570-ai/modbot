from __future__ import annotations

from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Agent, AgentJob, Group, GroupAdminRole, GroupSetting, ModerationLog, PluginEnabled, Warning
from bot.services.settings_service import SettingsService


class OwnerService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_groups(self) -> list[dict[str, Any]]:
        admin_count_sq = (
            select(func.count(GroupAdminRole.id))
            .where(GroupAdminRole.group_id == Group.id)
            .correlate(Group)
            .scalar_subquery()
        )
        warning_count_sq = (
            select(func.coalesce(func.sum(Warning.count), 0))
            .where(Warning.group_id == Group.id)
            .correlate(Group)
            .scalar_subquery()
        )
        plugin_count_sq = (
            select(func.count(PluginEnabled.id))
            .where(PluginEnabled.group_id == Group.id, PluginEnabled.enabled.is_(True))
            .correlate(Group)
            .scalar_subquery()
        )
        agent_count_sq = (
            select(func.count(Agent.id))
            .where(Agent.group_id == Group.id)
            .correlate(Group)
            .scalar_subquery()
        )
        last_activity_sq = (
            select(func.max(ModerationLog.created_at))
            .where(ModerationLog.group_id == Group.id)
            .correlate(Group)
            .scalar_subquery()
        )

        rows = (
            await self.session.execute(
                select(
                    Group.id,
                    Group.title,
                    Group.tg_group_id,
                    Group.is_active,
                    Group.created_at,
                    admin_count_sq.label("admin_count"),
                    warning_count_sq.label("warning_count"),
                    plugin_count_sq.label("plugin_count"),
                    agent_count_sq.label("agent_count"),
                    last_activity_sq.label("last_activity_at"),
                ).order_by(Group.is_active.desc(), Group.title.asc(), Group.id.asc())
            )
        ).all()

        return [
            {
                "id": row.id,
                "title": row.title,
                "tg_group_id": row.tg_group_id,
                "is_active": bool(row.is_active),
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "admin_count": int(row.admin_count or 0),
                "warning_count": int(row.warning_count or 0),
                "plugin_count": int(row.plugin_count or 0),
                "agent_count": int(row.agent_count or 0),
                "last_activity_at": row.last_activity_at.isoformat() if row.last_activity_at else None,
            }
            for row in rows
        ]

    async def get_group_details(self, group_id: int) -> dict[str, Any] | None:
        group = (await self.session.execute(select(Group).where(Group.id == group_id))).scalar_one_or_none()
        if group is None:
            return None

        admins = (
            await self.session.execute(
                select(GroupAdminRole.user_id, GroupAdminRole.role, GroupAdminRole.created_at)
                .where(GroupAdminRole.group_id == group_id)
                .order_by(GroupAdminRole.created_at.asc(), GroupAdminRole.id.asc())
            )
        ).all()
        settings = (
            await self.session.execute(
                select(GroupSetting.key, GroupSetting.value, GroupSetting.updated_at)
                .where(GroupSetting.group_id == group_id)
                .order_by(GroupSetting.key.asc())
            )
        ).all()
        plugins = (
            await self.session.execute(
                select(PluginEnabled.plugin_name, PluginEnabled.enabled, PluginEnabled.config)
                .where(PluginEnabled.group_id == group_id)
                .order_by(PluginEnabled.plugin_name.asc())
            )
        ).all()
        warnings = (
            await self.session.execute(
                select(Warning.user_id, Warning.count, Warning.reason, Warning.created_at)
                .where(Warning.group_id == group_id)
                .order_by(desc(Warning.created_at), desc(Warning.id))
                .limit(25)
            )
        ).all()
        logs = (
            await self.session.execute(
                select(
                    ModerationLog.action,
                    ModerationLog.target_user_id,
                    ModerationLog.admin_user_id,
                    ModerationLog.reason,
                    ModerationLog.details,
                    ModerationLog.created_at,
                )
                .where(ModerationLog.group_id == group_id)
                .order_by(desc(ModerationLog.created_at), desc(ModerationLog.id))
                .limit(25)
            )
        ).all()
        agents = (
            await self.session.execute(
                select(
                    Agent.id,
                    Agent.external_account_id,
                    Agent.telegram_user_id,
                    Agent.status,
                    Agent.auth_state,
                    Agent.updated_at,
                )
                .where(Agent.group_id == group_id)
                .order_by(Agent.id.asc())
            )
        ).all()

        return {
            "group": {
                "id": group.id,
                "title": group.title,
                "tg_group_id": group.tg_group_id,
                "is_active": bool(group.is_active),
                "created_at": group.created_at.isoformat() if group.created_at else None,
            },
            "admins": [
                {
                    "user_id": row.user_id,
                    "role": row.role,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in admins
            ],
            "settings": [
                {
                    "key": row.key,
                    "value": SettingsService.unwrap_value(row.value),
                    "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                }
                for row in settings
            ],
            "plugins": [
                {
                    "plugin_name": row.plugin_name,
                    "enabled": bool(row.enabled),
                    "config": row.config or {},
                }
                for row in plugins
            ],
            "warnings": [
                {
                    "user_id": row.user_id,
                    "count": row.count,
                    "reason": row.reason,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in warnings
            ],
            "recent_logs": [
                {
                    "action": row.action,
                    "target_user_id": row.target_user_id,
                    "admin_user_id": row.admin_user_id,
                    "reason": row.reason,
                    "details": row.details or {},
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in logs
            ],
            "agents": [
                {
                    "id": row.id,
                    "external_account_id": row.external_account_id,
                    "telegram_user_id": row.telegram_user_id,
                    "status": row.status,
                    "auth_state": row.auth_state,
                    "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                }
                for row in agents
            ],
        }

    async def stats(self) -> dict[str, int]:
        total_groups = (await self.session.execute(select(func.count(Group.id)))).scalar_one()
        active_groups = (
            await self.session.execute(select(func.count(Group.id)).where(Group.is_active.is_(True)))
        ).scalar_one()
        total_users = (await self.session.execute(select(func.count(func.distinct(GroupAdminRole.user_id))))).scalar_one()
        moderation_actions = (await self.session.execute(select(func.count(ModerationLog.id)))).scalar_one()
        open_warnings = (
            await self.session.execute(select(func.coalesce(func.sum(Warning.count), 0)))
        ).scalar_one()
        enabled_plugins = (
            await self.session.execute(select(func.count(PluginEnabled.id)).where(PluginEnabled.enabled.is_(True)))
        ).scalar_one()
        linked_agents = (await self.session.execute(select(func.count(Agent.id)))).scalar_one()
        pending_agent_jobs = (
            await self.session.execute(
                select(func.count(AgentJob.id)).where(AgentJob.status.in_(("pending", "queued", "running")))
            )
        ).scalar_one()

        return {
            "total_groups": int(total_groups or 0),
            "active_groups": int(active_groups or 0),
            "tracked_admins": int(total_users or 0),
            "moderation_actions": int(moderation_actions or 0),
            "open_warnings": int(open_warnings or 0),
            "enabled_plugins": int(enabled_plugins or 0),
            "linked_agents": int(linked_agents or 0),
            "pending_agent_jobs": int(pending_agent_jobs or 0),
        }

    async def disable_group(self, group_id: int) -> dict[str, Any] | None:
        group = (await self.session.execute(select(Group).where(Group.id == group_id))).scalar_one_or_none()
        if group is None:
            return None
        group.is_active = False
        await self.session.commit()
        return {
            "id": group.id,
            "title": group.title,
            "tg_group_id": group.tg_group_id,
            "is_active": bool(group.is_active),
        }

    async def list_all_agents(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        stmt = (
            select(
                Agent.id,
                Agent.external_account_id,
                Agent.telegram_user_id,
                Agent.phone_number,
                Agent.status,
                Agent.auth_state,
                Agent.created_at,
                Agent.updated_at,
                Group.title.label("group_title"),
                Group.id.label("group_id"),
            )
            .join(Group, Agent.group_id == Group.id)
            .order_by(Agent.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            {
                "id": row.id,
                "external_account_id": row.external_account_id,
                "telegram_user_id": row.telegram_user_id,
                "phone_number": row.phone_number,
                "status": row.status,
                "auth_state": row.auth_state,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                "group_title": row.group_title,
                "group_id": row.group_id,
            }
            for row in rows
        ]
