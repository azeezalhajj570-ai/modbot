from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import PluginEnabled


class PluginService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def is_enabled(self, group_id: int, plugin_name: str) -> bool:
        stmt = select(PluginEnabled.enabled).where(
            PluginEnabled.group_id == group_id,
            PluginEnabled.plugin_name == plugin_name,
        )
        enabled = (await self.session.execute(stmt)).scalar_one_or_none()
        return True if enabled is None else bool(enabled)

    async def set_enabled(self, group_id: int, plugin_name: str, enabled: bool) -> None:
        stmt = select(PluginEnabled).where(
            PluginEnabled.group_id == group_id,
            PluginEnabled.plugin_name == plugin_name,
        )
        existing = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing:
            existing.enabled = enabled
        else:
            self.session.add(PluginEnabled(group_id=group_id, plugin_name=plugin_name, enabled=enabled, config={}))
        await self.session.commit()

    async def list_group_plugins(self, group_id: int) -> dict[str, bool]:
        stmt = select(PluginEnabled.plugin_name, PluginEnabled.enabled).where(PluginEnabled.group_id == group_id)
        rows = (await self.session.execute(stmt)).all()
        return {row.plugin_name: bool(row.enabled) for row in rows}
