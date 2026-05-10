from __future__ import annotations

from enum import IntEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Group, GroupAdminRole, User


class PermissionLevel(IntEnum):
    MODERATOR = 10
    ADMIN = 20
    SUPER_ADMIN = 30
    OWNER = 40


ROLE_TO_LEVEL = {
    "moderator": PermissionLevel.MODERATOR,
    "admin": PermissionLevel.ADMIN,
    "super_admin": PermissionLevel.SUPER_ADMIN,
    "owner": PermissionLevel.OWNER,
}


ACTION_REQUIREMENTS = {
    "group.settings.update": PermissionLevel.ADMIN,
    "group.moderation.warn": PermissionLevel.MODERATOR,
    "group.moderation.ban": PermissionLevel.ADMIN,
    "system.plugin.control": PermissionLevel.OWNER,
    "system.global_ban": PermissionLevel.OWNER,
}


class PermissionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def user_level(self, group_id: int, user_id: int) -> PermissionLevel | None:
        stmt = select(GroupAdminRole.role).where(
            GroupAdminRole.group_id == group_id,
            GroupAdminRole.user_id == user_id,
        )
        role = (await self.session.execute(stmt)).scalar_one_or_none()
        if role:
            return ROLE_TO_LEVEL.get(role)

        owner_stmt = (
            select(Group.id)
            .join(User, User.id == Group.owner_user_id)
            .where(
                Group.id == group_id,
                User.tg_user_id == user_id,
            )
        )
        is_owner = (await self.session.execute(owner_stmt)).scalar_one_or_none()
        if is_owner is not None:
            return PermissionLevel.OWNER
        return None

    async def can(self, group_id: int, user_id: int, action: str) -> bool:
        required = ACTION_REQUIREMENTS.get(action, PermissionLevel.OWNER)
        current = await self.user_level(group_id, user_id)
        return current is not None and current >= required
