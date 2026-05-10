from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import GroupAccessRequirement
from bot.utils.i18n import t


class AccessGateService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_required_group_tg_ids(self, protected_group_id: int) -> list[int]:
        rows = (
            await self.session.execute(
                select(GroupAccessRequirement.required_group_tg_id).where(
                    GroupAccessRequirement.protected_group_id == protected_group_id
                )
            )
        ).scalars()
        return list(rows)

    async def list_all_required_group_tg_ids(self) -> list[int]:
        rows = (
            await self.session.execute(
                select(GroupAccessRequirement.required_group_tg_id).distinct()
            )
        ).scalars()
        return list(rows)

    async def is_required(self, protected_group_id: int, required_group_tg_id: int) -> bool:
        row = (
            await self.session.execute(
                select(GroupAccessRequirement.id).where(
                    GroupAccessRequirement.protected_group_id == protected_group_id,
                    GroupAccessRequirement.required_group_tg_id == required_group_tg_id,
                )
            )
        ).scalar_one_or_none()
        return row is not None

    async def add_required_group(self, protected_group_id: int, required_group_tg_id: int) -> None:
        if await self.is_required(protected_group_id, required_group_tg_id):
            return
        self.session.add(
            GroupAccessRequirement(
                protected_group_id=protected_group_id,
                required_group_tg_id=required_group_tg_id,
            )
        )
        await self.session.commit()

    async def remove_required_group(self, protected_group_id: int, required_group_tg_id: int) -> None:
        await self.session.execute(
            delete(GroupAccessRequirement).where(
                GroupAccessRequirement.protected_group_id == protected_group_id,
                GroupAccessRequirement.required_group_tg_id == required_group_tg_id,
            )
        )
        await self.session.commit()

    async def clear_required_groups(self, protected_group_id: int) -> None:
        await self.session.execute(
            delete(GroupAccessRequirement).where(
                GroupAccessRequirement.protected_group_id == protected_group_id
            )
        )
        await self.session.commit()


def build_access_gate_notice(lang: str, required_group_titles: list[str]) -> str:
    lines = [t("access_gate_blocked", lang)]
    if required_group_titles:
        lines.append(t("access_gate_required_groups", lang, groups=", ".join(required_group_titles)))
    return "\n".join(lines)


def build_private_access_gate_notice(
    lang: str,
    required_group_titles: list[str],
    *,
    member_name: str | None = None,
) -> str:
    lines = [t("private_access_gate_blocked", lang, member=member_name or "Member")]
    if required_group_titles:
        lines.append(t("access_gate_required_groups", lang, groups=", ".join(required_group_titles)))
    return "\n".join(lines)


def build_access_gate_buttons(required_groups: list[tuple[str, str]]) -> InlineKeyboardMarkup | None:
    if not required_groups:
        return None

    kb = InlineKeyboardBuilder()
    for title, url in required_groups:
        kb.button(text=title, url=url)
    kb.adjust(1)
    return kb.as_markup()
