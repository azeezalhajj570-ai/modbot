"""Handler for Telegram ChatJoinRequest updates with verification gate."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import ChatJoinRequest
from sqlalchemy import select, and_
import structlog

from bot.db.models import Group, GroupAdminRole, User, GroupSubscriber
from bot.db.session import SessionLocal
from bot.services.access_gate_service import AccessGateService
from bot.services.join_request_service import (
    JoinRequestService,
    _chat_id_candidates,
    build_verify_keyboard,
    resolve_group_by_tg_id,
)
from bot.services.settings_service import SettingsService
from bot.utils.i18n import t

router = Router(name="join_request")
logger = structlog.get_logger(__name__)


async def _setting_enabled(session, group_id: int, key: str, default: bool = True) -> bool:
    value = await SettingsService(session).get_one(group_id, key)
    return default if value is None else bool(value)


async def _get_admin_ids(session, group_id: int) -> list[int]:
    """Get all admin user TG IDs for a managed group."""
    # Get group admins
    admin_stmt = (
        select(GroupAdminRole.user_id)
        .where(GroupAdminRole.group_id == group_id)
    )
    admin_ids = list(
        (await session.execute(admin_stmt)).scalars().all()
    )
    # Get group owner
    owner_stmt = (
        select(User.tg_user_id)
        .join(Group, Group.owner_user_id == User.id)
        .where(Group.id == group_id)
    )
    owner_id = (await session.execute(owner_stmt)).scalar_one_or_none()
    if owner_id:
        admin_ids.append(int(owner_id))
    return list(set(admin_ids))


async def _is_group_member(
    bot,
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


async def _verify_membership(
    bot,
    user_id: int,
    required_group_tg_ids: list[int],
) -> list[int]:
    """Check which required groups the user is actually a member of. Returns verified TG IDs."""
    verified: list[int] = []
    for rg_id in required_group_tg_ids:
        if await _is_group_member(bot, rg_id, user_id):
            verified.append(rg_id)
    return verified


@router.chat_join_request()
async def on_chat_join_request(event: ChatJoinRequest) -> None:
    """Handle join requests for protected groups.

    If join request verification is enabled and the group has required groups configured,
    the request is NOT immediately approved. Instead:
    1. A pending record is created
    2. The user is sent a message with links to required groups + a check button
    3. Admins are notified of the pending request
    """
    user = event.from_user
    chat = event.chat
    bot = event.bot
    lang = "en"  # default; can be extended per-user language resolution

    async with SessionLocal() as session:
        group = await resolve_group_by_tg_id(session, chat.id)
        if group is None:
            # Not a managed group, let Telegram handle it normally
            return

        # 1. Paid Group Access check
        from bot.services.group_subscription_service import GroupSubscriptionService
        from bot.db.models import GroupSubscriberStatus
        
        gs_service = GroupSubscriptionService(session)
        paid_settings = await gs_service.get_settings(group.id)
        
        if paid_settings.enabled:
            # Check if user has active subscription
            subscriber_stmt = select(GroupSubscriber).where(
                and_(
                    GroupSubscriber.group_id == group.id,
                    GroupSubscriber.user_id == user.id,
                    GroupSubscriber.status == GroupSubscriberStatus.ACTIVE
                )
            )
            subscriber = (await session.execute(subscriber_stmt)).scalar_one_or_none()
            
            if not subscriber:
                # User not subscribed, decline and notify
                # Actually declining might be too harsh, maybe just ignore or notify?
                # Usually if it's a join request, we want to approve only if paid.
                # If bot creates single-use links, this join request might be via direct link or search.
                try:
                    await bot.send_message(
                        chat_id=user.id,
                        text=f"This group '{group.title}' requires a paid subscription to join. Please use /subscribe to see available plans."
                    )
                except Exception:
                    pass
                
                logger.info(
                    "joinreq_declined_unpaid",
                    group_id=group.id,
                    user_tg_id=user.id,
                )
                # We don't necessarily 'decline' via API yet to avoid blocking future attempts 
                # unless that's intended. Telegram auto-declines after 24h if no action.
                return

        # 2. Existing join request verification
        # Check if join request verification is enabled
        join_req_enabled = await _setting_enabled(session, group.id, "join_request_verify", default=False)
        if not join_req_enabled:
            return

        # Get required groups for this protected group
        required_group_tg_ids = await AccessGateService(session).list_required_group_tg_ids(group.id)
        if not required_group_tg_ids:
            # No required groups configured, let Telegram handle normally
            return

        service = JoinRequestService(session)

        # Check if user is already in all required groups
        verified_ids = await _verify_membership(bot, user.id, required_group_tg_ids)
        missing_ids = [g for g in required_group_tg_ids if g not in verified_ids]

        if not missing_ids:
            # User already in all required groups — auto-approve
            await event.approve()
            logger.info(
                "joinreq_auto_approved",
                protected_group_tg_id=chat.id,
                user_tg_id=user.id,
                reason="all_required_groups_joined",
            )
            return

        # Clean up stale non-pending records for this user+group
        await service.clear_stale(chat.id, user.id)

        # Check if there's already a pending request
        existing = await service.find_pending(
            protected_group_tg_id=chat.id,
            user_tg_id=user.id,
        )
        if existing:
            # Already pending, send reminder with updated links
            approval = existing[0]
            await service.update_verified_groups(approval.id, verified_ids)
            keyboard = await build_verify_keyboard(bot, approval, lang)
            try:
                await bot.send_message(
                    chat_id=user.id,
                    text=t("joinreq_pending_reminder", lang, group=group.title or str(chat.id)),
                    reply_markup=keyboard.as_markup(),
                )
            except Exception:
                logger.warning(
                    "joinreq_reminder_failed",
                    user_tg_id=user.id,
                    approval_id=approval.id,
                )
            return

        # Create a new pending request
        invite_url = None
        if getattr(event, "invite_link", None):
            invite_url = getattr(event.invite_link, "url", None)

        approval = await service.create_pending(
            protected_group_tg_id=chat.id,
            user_tg_id=user.id,
            first_name=user.first_name,
            username=user.username,
            invite_link=invite_url,
            required_group_tg_ids=required_group_tg_ids,
        )
        await service.update_verified_groups(approval.id, verified_ids)

        # Notify the user that they need to join required groups
        keyboard = await build_verify_keyboard(bot, approval, lang)
        try:
            await bot.send_message(
                chat_id=user.id,
                text=t("joinreq_verification_required", lang, group=group.title or str(chat.id)),
                reply_markup=keyboard.as_markup(),
            )
        except Exception:
            logger.warning(
                "joinreq_user_notify_failed",
                user_tg_id=user.id,
                approval_id=approval.id,
            )

        # Notify admins of the pending request
        try:
            admin_ids = await _get_admin_ids(session, group.id)
            for admin_id in admin_ids[:5]:  # Limit to 5 admins to avoid spam
                try:
                    await bot.send_message(
                        chat_id=admin_id,
                        text=t(
                            "joinreq_admin_notify",
                            lang,
                            user=user.first_name or str(user.id),
                            group=group.title or str(chat.id),
                        ),
                    )
                except Exception:
                    continue
        except Exception:
            pass

        logger.info(
            "joinreq_pending_created",
            protected_group_tg_id=chat.id,
            user_tg_id=user.id,
            approval_id=approval.id,
            required_groups=required_group_tg_ids,
        )
