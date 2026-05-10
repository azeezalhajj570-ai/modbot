"""Callback handlers for join request admin actions (approve/decline/verify/refresh)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
import structlog

from bot.db.session import SessionLocal
from bot.services.join_request_service import (
    JoinRequestService,
    _chat_id_candidates,
    build_verify_keyboard,
    resolve_group_by_tg_id,
    verify_membership,
)
from bot.services.permission_service import PermissionService
from bot.utils.i18n import t

router = Router(name="join_request_callbacks")
logger = structlog.get_logger(__name__)


def _parse_callback(data: str) -> tuple[str, int]:
    """Parse callback data like 'joinreq_approve:123' into ('approve', 123)."""
    action, _, value = data.partition(":")
    return action, int(value)


@router.callback_query(F.data.startswith("joinreq_"))
async def handle_joinreq_callback(call: CallbackQuery) -> None:
    """Handle join request callback actions."""
    action, approval_id = _parse_callback(call.data)
    lang = "en"
    user = call.from_user

    async with SessionLocal() as session:
        service = JoinRequestService(session)
        approval = await service.find_one(approval_id)

        if approval is None:
            await call.answer(t("joinreq_expired", lang), show_alert=True)
            return

        if action == "joinreq_approve":
            await _handle_approve(call, session, service, approval, user.id, lang)
        elif action == "joinreq_decline":
            await _handle_decline(call, session, service, approval, user.id, lang)
        elif action == "joinreq_verify":
            await _handle_verify(call, session, service, approval, lang)
        elif action == "joinreq_refresh":
            await _handle_refresh(call, session, service, approval, lang)
        else:
            await call.answer(t("unknown_action", lang))
            return


async def _handle_approve(
    call: CallbackQuery,
    session,
    service: JoinRequestService,
    approval,
    admin_id: int,
    lang: str,
) -> None:
    """Admin approves the join request."""
    # Approve the request in DB
    await service.approve(approval.id, approved_by=admin_id)

    # Approve the Telegram join request
    try:
        await call.bot.approve_chat_join_request(
            chat_id=approval.protected_group_tg_id,
            user_id=approval.user_tg_id,
        )
    except Exception as exc:
        logger.warning(
            "joinreq_telegram_approve_failed",
            approval_id=approval.id,
            error=str(exc),
        )
        await call.answer(t("joinreq_approve_failed", lang), show_alert=True)
        return

    # Notify the user
    try:
        await call.bot.send_message(
            chat_id=approval.user_tg_id,
            text=t("joinreq_approved_notify", lang, group=str(approval.protected_group_tg_id)),
        )
    except Exception:
        pass

    await call.answer(t("joinreq_approved", lang))
    # Update the callback message to reflect approval
    try:
        await call.message.edit_text(
            t("joinreq_approved_done", lang, user=approval.first_name or str(approval.user_tg_id)),
        )
    except Exception:
        pass

    logger.info(
        "joinreq_admin_approved",
        approval_id=approval.id,
        admin_id=admin_id,
    )


async def _handle_decline(
    call: CallbackQuery,
    session,
    service: JoinRequestService,
    approval,
    admin_id: int,
    lang: str,
) -> None:
    """Admin declines the join request."""
    # Decline in DB
    await service.decline(approval.id, declined_by=admin_id)

    # Decline the Telegram join request
    try:
        await call.bot.decline_chat_join_request(
            chat_id=approval.protected_group_tg_id,
            user_id=approval.user_tg_id,
        )
    except Exception as exc:
        logger.warning(
            "joinreq_telegram_decline_failed",
            approval_id=approval.id,
            error=str(exc),
        )
        await call.answer(t("joinreq_decline_failed", lang), show_alert=True)
        return

    # Notify the user
    try:
        await call.bot.send_message(
            chat_id=approval.user_tg_id,
            text=t("joinreq_declined_notify", lang, group=str(approval.protected_group_tg_id)),
        )
    except Exception:
        pass

    await call.answer(t("joinreq_declined", lang))
    try:
        await call.message.edit_text(
            t("joinreq_declined_done", lang, user=approval.first_name or str(approval.user_tg_id)),
        )
    except Exception:
        pass

    logger.info(
        "joinreq_admin_declined",
        approval_id=approval.id,
        admin_id=admin_id,
    )


async def _handle_verify(
    call: CallbackQuery,
    session,
    service: JoinRequestService,
    approval,
    lang: str,
) -> None:
    """Show admin the verification status of a pending request."""
    verified_ids = await verify_membership(call.bot, approval)
    await service.update_verified_groups(approval.id, verified_ids)

    required_ids = set()
    if approval.required_group_tg_ids:
        required_ids = {int(x) for x in approval.required_group_tg_ids.split(",") if x.strip()}

    status_lines = []
    for rg_id in sorted(required_ids):
        is_joined = rg_id in verified_ids
        icon = "✅" if is_joined else "⬜"
        title = str(rg_id)
        for candidate_id in _chat_id_candidates(rg_id):
            try:
                chat = await call.bot.get_chat(candidate_id)
                title = getattr(chat, "title", str(rg_id))
                break
            except Exception:
                continue
        status_lines.append(f"{icon} {title}")

    verified_count = len(verified_ids)
    total_count = len(required_ids)

    text = (
        f"🔍 {approval.first_name or approval.user_tg_id}"
        f"{' (@' + approval.username + ')' if approval.username else ''}\n"
        f"{t('joinreq_verification_status', lang)}\n"
        f"{verified_count}/{total_count}\n\n"
        + "\n".join(status_lines)
    )

    # Check if all required groups are joined
    if verified_count >= total_count:
        text += f"\n\n✅ {t('joinreq_all_verified', lang)}"
        # Add approve button
        kb = InlineKeyboardBuilder()
        kb.button(
            text=f"✅ {t('confirm', lang)}",
            callback_data=f"joinreq_approve:{approval.id}",
        )
        kb.adjust(1)
        await call.message.edit_text(text, reply_markup=kb.as_markup())
    else:
        text += f"\n\n⚠️ {t('joinreq_not_all_verified', lang)}"
        await call.answer(t("joinreq_verified_updated", lang, count=verified_count))


async def _handle_refresh(
    call: CallbackQuery,
    session,
    service: JoinRequestService,
    approval,
    lang: str,
) -> None:
    """User presses refresh to check their membership in required groups."""
    verified_ids = await verify_membership(call.bot, approval)
    await service.update_verified_groups(approval.id, verified_ids)

    required_ids = set()
    if approval.required_group_tg_ids:
        required_ids = {int(x) for x in approval.required_group_tg_ids.split(",") if x.strip()}

    missing_ids = required_ids - set(verified_ids)
    verified_count = len(verified_ids)
    total_count = len(required_ids)

    if not missing_ids:
        # All groups joined — send success message
        await call.message.edit_text(
            t("joinreq_all_joined", lang, group=str(approval.protected_group_tg_id)),
        )
        await call.answer(t("joinreq_all_joined_notify", lang))
        logger.info(
            "joinreq_all_verified_auto",
            approval_id=approval.id,
            user_tg_id=approval.user_tg_id,
        )
        return

    # Update keyboard with remaining missing groups
    keyboard = await build_verify_keyboard(call.bot, approval, lang)
    await call.message.edit_reply_markup(reply_markup=keyboard.as_markup())

    await call.answer(
        t("joinreq_still_missing", lang, count=len(missing_ids)),
        show_alert=True,
    )
