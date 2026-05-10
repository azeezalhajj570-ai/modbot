"""Service for managing join request approvals with verification."""

from __future__ import annotations

from datetime import datetime

from aiogram import Bot
from aiogram.types import ChatMemberAdministrator, ChatMemberOwner
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Group, JoinRequestApproval
from bot.utils.i18n import t


class JoinRequestService:
    """Manages pending join requests that require group-membership verification."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_pending(
        self,
        protected_group_tg_id: int,
        user_tg_id: int,
        first_name: str | None,
        username: str | None,
        invite_link: str | None,
        required_group_tg_ids: list[int],
    ) -> JoinRequestApproval:
        """Create a new pending join request record."""
        approval = JoinRequestApproval(
            protected_group_tg_id=protected_group_tg_id,
            user_tg_id=user_tg_id,
            first_name=first_name,
            username=username,
            invite_link=invite_link,
            required_group_tg_ids=",".join(str(g) for g in required_group_tg_ids),
            verified_group_tg_ids="",
            status="pending",
        )
        self.session.add(approval)
        await self.session.commit()
        await self.session.refresh(approval)
        return approval

    async def find_pending(
        self,
        protected_group_tg_id: int | None = None,
        user_tg_id: int | None = None,
    ) -> list[JoinRequestApproval]:
        """Find pending approvals, optionally filtered."""
        stmt = select(JoinRequestApproval).where(
            JoinRequestApproval.status == "pending"
        )
        if protected_group_tg_id is not None:
            stmt = stmt.where(
                JoinRequestApproval.protected_group_tg_id == protected_group_tg_id
            )
        if user_tg_id is not None:
            stmt = stmt.where(JoinRequestApproval.user_tg_id == user_tg_id)
        stmt = stmt.order_by(JoinRequestApproval.created_at.desc())
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows)

    async def find_one(
        self,
        approval_id: int,
    ) -> JoinRequestApproval | None:
        """Find a single approval by ID."""
        return (
            await self.session.execute(
                select(JoinRequestApproval).where(
                    JoinRequestApproval.id == approval_id
                )
            )
        ).scalar_one_or_none()

    async def update_verified_groups(
        self,
        approval_id: int,
        verified_group_tg_ids: list[int],
    ) -> None:
        """Update which required groups the user has been verified in."""
        approval = await self.find_one(approval_id)
        if approval is None:
            return
        approval.verified_group_tg_ids = ",".join(str(g) for g in verified_group_tg_ids)
        approval.updated_at = datetime.utcnow()
        await self.session.commit()

    async def approve(
        self,
        approval_id: int,
        approved_by: int | None = None,
    ) -> JoinRequestApproval | None:
        """Mark an approval as approved."""
        approval = await self.find_one(approval_id)
        if approval is None:
            return None
        approval.status = "approved"
        approval.approved_by = approved_by
        approval.updated_at = datetime.utcnow()
        await self.session.commit()
        await self.session.refresh(approval)
        return approval

    async def decline(
        self,
        approval_id: int,
        reason: str | None = None,
        declined_by: int | None = None,
    ) -> JoinRequestApproval | None:
        """Mark an approval as declined."""
        approval = await self.find_one(approval_id)
        if approval is None:
            return None
        approval.status = "declined"
        approval.decline_reason = reason
        approval.approved_by = declined_by
        approval.updated_at = datetime.utcnow()
        await self.session.commit()
        await self.session.refresh(approval)
        return approval

    async def clear_stale(
        self,
        protected_group_tg_id: int,
        user_tg_id: int,
    ) -> None:
        """Remove stale non-pending records for this user+group pair."""
        await self.session.execute(
            delete(JoinRequestApproval).where(
                JoinRequestApproval.protected_group_tg_id == protected_group_tg_id,
                JoinRequestApproval.user_tg_id == user_tg_id,
                JoinRequestApproval.status != "pending",
            )
        )
        await self.session.commit()


def build_admin_pending_keyboard(
    lang: str,
    approvals: list[JoinRequestApproval],
) -> InlineKeyboardBuilder:
    """Build inline keyboard showing pending join requests with action buttons."""
    kb = InlineKeyboardBuilder()
    for approval in approvals:
        display_name = approval.first_name or str(approval.user_tg_id)
        if approval.username:
            display_name += f" (@{approval.username})"
        # Verify button
        kb.button(
            text=f"🔍 {display_name}",
            callback_data=f"joinreq_verify:{approval.id}",
        )
        # Approve button
        kb.button(
            text=f"✅ {display_name}",
            callback_data=f"joinreq_approve:{approval.id}",
        )
        # Decline button
        kb.button(
            text=f"❌ {display_name}",
            callback_data=f"joinreq_decline:{approval.id}",
        )
    kb.adjust(1)
    return kb


def build_pending_list_text(
    lang: str,
    group_title: str,
    approvals: list[JoinRequestApproval],
    all_required_tg_ids: list[int],
) -> str:
    """Build a formatted message listing pending join requests."""
    lines = [t("joinreq_pending_title", lang, group=group_title)]
    if not approvals:
        lines.append(t("joinreq_no_pending", lang))
        return "\n".join(lines)

    for approval in approvals:
        display_name = approval.first_name or str(approval.user_tg_id)
        if approval.username:
            display_name += f" (@{approval.username})"

        verified_set = set()
        if approval.verified_group_tg_ids:
            verified_set = {
                int(x) for x in approval.verified_group_tg_ids.split(",") if x.strip()
            }

        status_icons = []
        for rg_id in all_required_tg_ids:
            if rg_id in verified_set:
                status_icons.append("✅")
            else:
                status_icons.append("⬜")

        joined_count = len(verified_set)
        total_count = len(all_required_tg_ids)
        lines.append(
            f"• {display_name} (`{approval.user_tg_id}`) — "
            f"{joined_count}/{total_count} {t('joinreq_verified', lang)} "
            f"{' '.join(status_icons)}"
        )
    return "\n".join(lines)


async def build_verify_keyboard(
    bot: Bot,
    approval: JoinRequestApproval,
    lang: str,
) -> InlineKeyboardBuilder:
    """Build inline keyboard with join links for required groups the user hasn't joined yet."""
    kb = InlineKeyboardBuilder()
    required_ids = set()
    if approval.required_group_tg_ids:
        required_ids = {
            int(x) for x in approval.required_group_tg_ids.split(",") if x.strip()
        }
    verified_ids = set()
    if approval.verified_group_tg_ids:
        verified_ids = {
            int(x) for x in approval.verified_group_tg_ids.split(",") if x.strip()
        }
    missing_ids = required_ids - verified_ids

    for rg_id in missing_ids:
        title = str(rg_id)
        url: str | None = None
        # Try to resolve group info
        for candidate_id in _chat_id_candidates(rg_id):
            try:
                chat = await bot.get_chat(candidate_id)
                chat_username = getattr(chat, "username", None)
                if chat_username:
                    url = f"https://t.me/{chat_username}"
                    title = getattr(chat, "title", str(rg_id))
                    break
            except Exception:
                continue
        if not url:
            for candidate_id in _chat_id_candidates(rg_id):
                try:
                    invite_link = await bot.export_chat_invite_link(candidate_id)
                    if invite_link:
                        url = str(invite_link)
                        break
                except Exception:
                    continue
        kb.button(text=f"📌 {title}", url=url)

    # Refresh verification status button
    kb.button(
        text=t("joinreq_check_membership", lang),
        callback_data=f"joinreq_refresh:{approval.id}",
    )
    kb.adjust(1)
    return kb


async def _is_group_member(
    bot: Bot,
    chat_id: int,
    user_id: int,
) -> bool:
    """Check if a user is a member of the given chat."""
    for candidate_id in _chat_id_candidates(chat_id):
        try:
            member = await bot.get_chat_member(candidate_id, user_id)
            status = str(getattr(member, "status", "")).lower()
            if status in {"member", "administrator", "creator", "owner"}:
                return True
            if status == "restricted" and getattr(member, "is_member", False):
                return True
        except Exception:
            continue
    return False


def _chat_id_candidates(chat_id: int) -> tuple[int, ...]:
    """Generate candidate chat IDs for lookup."""
    text = str(chat_id)
    if text.startswith("-100"):
        legacy_id = -int(text[4:])
        return (chat_id, legacy_id)
    if chat_id < 0:
        return (chat_id, int(f"-100{abs(chat_id)}"))
    return (chat_id,)


async def verify_membership(
    bot: Bot,
    approval: JoinRequestApproval,
) -> list[int]:
    """Check which required groups the user is actually a member of. Returns verified TG IDs."""
    required_ids: set[int] = set()
    if approval.required_group_tg_ids:
        required_ids = {
            int(x) for x in approval.required_group_tg_ids.split(",") if x.strip()
        }
    verified: list[int] = []
    for rg_id in required_ids:
        if await _is_group_member(bot, rg_id, approval.user_tg_id):
            verified.append(rg_id)
    return verified


async def is_group_admin(
    bot: Bot,
    chat_id: int,
    user_id: int,
) -> bool:
    """Check if user is an admin in the chat."""
    for candidate_id in _chat_id_candidates(chat_id):
        try:
            member = await bot.get_chat_member(candidate_id, user_id)
            if isinstance(member, (ChatMemberAdministrator, ChatMemberOwner)):
                return True
        except Exception:
            continue
    return False


async def resolve_group_by_tg_id(
    session: AsyncSession,
    tg_group_id: int,
) -> Group | None:
    """Resolve a Group by its Telegram chat ID."""
    text = str(tg_group_id)
    candidate_ids: list[int] = [tg_group_id]
    if text.startswith("-100"):
        candidate_ids.append(-int(text[4:]))
    elif tg_group_id < 0:
        candidate_ids.append(int(f"-100{abs(tg_group_id)}"))

    rows = (
        await session.execute(
            select(Group).where(Group.tg_group_id.in_(candidate_ids))
        )
    ).scalars().all()
    if not rows:
        return None
    for group in rows:
        if group.tg_group_id == tg_group_id:
            return group
    return rows[0]
