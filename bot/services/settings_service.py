from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import GroupSetting

T = TypeVar("T")


@dataclass(frozen=True)
class GroupSettingAdapter(Generic[T]):
    default: T
    parse: Callable[[Any, T], T]

    def read(self, value: Any) -> T:
        return self.parse(SettingsService.unwrap_value(value), self.default)


def parse_bool_setting(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    return bool(value)


def parse_int_setting(value: Any, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class SettingsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def unwrap_value(value: Any) -> Any:
        if isinstance(value, dict) and "value" in value:
            return value.get("value")
        return value

    async def get_all(self, group_id: int) -> dict[str, Any]:
        stmt = select(GroupSetting.key, GroupSetting.value).where(GroupSetting.group_id == group_id)
        rows = (await self.session.execute(stmt)).all()
        return {row.key: self.unwrap_value(row.value) for row in rows}

    async def get_all_typed(
        self,
        group_id: int,
        *,
        adapters: dict[str, GroupSettingAdapter[Any]],
    ) -> dict[str, Any]:
        values = await self.get_all(group_id)
        return {
            key: adapters[key].read(values.get(key))
            for key in adapters
        }

    async def get_one(self, group_id: int, key: str) -> Any:
        stmt = select(GroupSetting.value).where(GroupSetting.group_id == group_id, GroupSetting.key == key)
        value = (await self.session.execute(stmt)).scalar_one_or_none()
        return self.unwrap_value(value) if value is not None else None

    async def get_typed(self, group_id: int, key: str, *, adapter: GroupSettingAdapter[T]) -> T:
        return adapter.read(await self.get_one(group_id, key))

    async def set_value(self, group_id: int, key: str, value: Any) -> None:
        stmt = select(GroupSetting).where(GroupSetting.group_id == group_id, GroupSetting.key == key)
        existing = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing:
            existing.value = {"value": value}
            existing.updated_at = datetime.utcnow()
        else:
            self.session.add(GroupSetting(group_id=group_id, key=key, value={"value": value}))
        await self.session.commit()
