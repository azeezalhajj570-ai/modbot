from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.runtime.audit import AuditEntry, ModerationLogAuditSink, RuntimeAuditService
from bot.db.models import GroupAdminRole
from bot.services.permission_service import PermissionService


class AdminRoleService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def set_member_role(
        self,
        *,
        group_id: int,
        actor_user_id: int,
        user_id: int,
        role: str,
    ) -> dict[str, Any]:
        requester = await PermissionService(self.session).user_level(group_id, actor_user_id)
        if requester is None or requester < 30:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only super admins can manage roles")

        existing = (
            await self.session.execute(
                select(GroupAdminRole).where(GroupAdminRole.group_id == group_id, GroupAdminRole.user_id == user_id)
            )
        ).scalar_one_or_none()
        if existing:
            existing.role = role
        else:
            self.session.add(GroupAdminRole(group_id=group_id, user_id=user_id, role=role))

        await RuntimeAuditService(ModerationLogAuditSink(self.session)).record(
            AuditEntry(
                action="set_admin_role",
                group_id=group_id,
                actor_user_id=actor_user_id,
                target_user_id=user_id,
                domain="admin",
                event_type="admin.member_role_updated",
                action_type="set_member_role",
                source_runtime="admin.service",
                details={
                    "new_role": role,
                    "source": "webapp",
                    "selected_actions": ["set_member_role"],
                    "guard_outcomes": [],
                    "execution_result": {"new_role": role},
                },
            )
        )
        await self.session.commit()
        return {"status": "ok"}
