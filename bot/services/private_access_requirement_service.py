from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Group, PrivateAccessRequirement


class PrivateAccessRequirementService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_required_group_tg_ids(self) -> list[int]:
        rows = (
            await self.session.execute(
                select(PrivateAccessRequirement.required_group_tg_id).order_by(
                    PrivateAccessRequirement.required_group_tg_id.asc()
                )
            )
        ).scalars()
        return list(rows)

    async def replace_required_groups(self, required_group_tg_ids: list[int]) -> list[int]:
        requested = list(dict.fromkeys(int(value) for value in required_group_tg_ids))
        await self.session.execute(delete(PrivateAccessRequirement))
        self.session.add_all(
            [PrivateAccessRequirement(required_group_tg_id=tg_group_id) for tg_group_id in requested]
        )
        await self.session.commit()
        return requested

    async def list_candidate_groups(self) -> list[dict[str, int | str | bool | None]]:
        rows = (
            await self.session.execute(
                select(Group.id, Group.title, Group.tg_group_id, Group.is_active)
                .where(Group.is_active.is_(True))
                .order_by(Group.title.asc(), Group.id.asc())
            )
        ).all()
        return [
            {
                "id": int(row.id),
                "title": row.title,
                "tg_group_id": int(row.tg_group_id),
                "is_active": bool(row.is_active),
            }
            for row in rows
        ]
