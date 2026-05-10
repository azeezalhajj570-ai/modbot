from __future__ import annotations

from aiogram.types import Message
from sqlalchemy import select

from bot.db.models import Group
from bot.db.session import SessionLocal
from bot.services.access_gate_service import (
    build_access_gate_buttons,
    build_private_access_gate_notice,
)
from bot.services.group_service import tg_group_id_candidates
from bot.services.private_access_requirement_service import PrivateAccessRequirementService


def _chat_id_candidates(chat_id: int) -> tuple[int, ...]:
    text = str(chat_id)
    if text.startswith("-100"):
        legacy_id = -int(text[4:])
        return (chat_id, legacy_id)
    if chat_id < 0:
        return (chat_id, int(f"-100{abs(chat_id)}"))
    return (chat_id,)


def _is_group_member(member: object) -> bool:
    status = str(getattr(member, "status", "")).lower()
    if status in {"member", "administrator", "creator", "owner"}:
        return True
    if status == "restricted":
        return bool(getattr(member, "is_member", False))
    return False


async def _required_group_titles(session, required_group_tg_ids: list[int]) -> list[str]:
    titles: list[str] = []
    for required_group_tg_id in required_group_tg_ids:
        rows = (
            await session.execute(select(Group.title).where(Group.tg_group_id.in_(tg_group_id_candidates(required_group_tg_id))))
        ).scalars().all()
        titles.append(str(rows[0]) if rows else str(required_group_tg_id))
    return titles


async def _required_group_targets(bot, session, required_group_tg_ids: list[int]) -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []
    for required_group_tg_id in required_group_tg_ids:
        rows = (
            await session.execute(select(Group.title).where(Group.tg_group_id.in_(tg_group_id_candidates(required_group_tg_id))))
        ).scalars().all()
        title = str(rows[0]) if rows else str(required_group_tg_id)
        url: str | None = None
        for candidate_id in _chat_id_candidates(required_group_tg_id):
            try:
                chat = await bot.get_chat(candidate_id)
                username = getattr(chat, "username", None)
                if username:
                    url = f"https://t.me/{username}"
                    break
            except Exception:
                continue
        if not url:
            for candidate_id in _chat_id_candidates(required_group_tg_id):
                try:
                    invite_link = await bot.export_chat_invite_link(candidate_id)
                    if invite_link:
                        url = str(invite_link)
                        break
                except Exception:
                    continue
        if url:
            targets.append((title, url))
    return targets


async def enforce_private_access_gate(message: Message, lang: str) -> bool:
    if message.chat.type != "private" or not message.from_user:
        return False

    async with SessionLocal() as session:
        required_groups = await PrivateAccessRequirementService(session).list_required_group_tg_ids()
        if not required_groups:
            return False

        missing_required_groups: list[int] = []
        for required_group_tg_id in required_groups:
            is_member = False
            for candidate_id in _chat_id_candidates(required_group_tg_id):
                try:
                    member = await message.bot.get_chat_member(candidate_id, message.from_user.id)
                    if _is_group_member(member):
                        is_member = True
                        break
                except Exception:
                    continue
            if not is_member:
                missing_required_groups.append(required_group_tg_id)

        if not missing_required_groups:
            return False

        required_group_titles = await _required_group_titles(session, missing_required_groups)
        required_group_targets = await _required_group_targets(message.bot, session, missing_required_groups)
        await message.answer(
            build_private_access_gate_notice(
                lang,
                required_group_titles,
                member_name=getattr(message.from_user, "full_name", None) or getattr(message.from_user, "first_name", None),
            ),
            reply_markup=build_access_gate_buttons(required_group_targets),
        )
        return True
