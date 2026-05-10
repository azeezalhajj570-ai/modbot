from __future__ import annotations

import pytest

from bot.db.models import GroupAdminRole
from bot.services.permission_service import PermissionService


@pytest.mark.asyncio
async def test_owner_can_control_system_plugins(patch_db_dependencies, seeded_group, db_session) -> None:
    service = PermissionService(db_session)
    assert await service.can(seeded_group["group_id"], seeded_group["user_id"], "system.plugin.control") is True


@pytest.mark.asyncio
async def test_moderator_cannot_perform_owner_action(patch_db_dependencies, seeded_group, db_session) -> None:
    db_session.add(GroupAdminRole(group_id=seeded_group["group_id"], user_id=3001, role="moderator"))
    await db_session.commit()

    service = PermissionService(db_session)
    assert await service.can(seeded_group["group_id"], 3001, "system.plugin.control") is False


@pytest.mark.asyncio
async def test_moderator_can_warn_but_not_ban(patch_db_dependencies, seeded_group, db_session) -> None:
    db_session.add(GroupAdminRole(group_id=seeded_group["group_id"], user_id=3002, role="moderator"))
    await db_session.commit()

    service = PermissionService(db_session)
    assert await service.can(seeded_group["group_id"], 3002, "group.moderation.warn") is True
    assert await service.can(seeded_group["group_id"], 3002, "group.moderation.ban") is False
