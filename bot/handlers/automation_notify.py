from __future__ import annotations

from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Filter
from aiogram.types import CallbackQuery, Message
import structlog

from bot.agents.runtime import UserAgentExecutor
from bot.agents.session import SessionManager
from bot.db import session as db_session
from bot.services.notify_destination_approval_service import NotifyDestinationApprovalService
from bot.services.task_activity_service import TaskActivityService


router = Router(name="automation_notify")
logger = structlog.get_logger(__name__)
_RESERVED_MODERATION_REPLIES = {
    "ban",
    "/ban",
    "ban user",
    "/ban user",
    "mute",
    "/mute",
    "mute user",
    "/mute user",
    "حظر",
    "/حظر",
    "حظر المستخدم",
    "/حظر المستخدم",
    "كتم",
    "/كتم",
    "كتم المستخدم",
    "/كتم المستخدم",
}


def _user_label(user) -> str:
    if user is None:
        return "unknown"
    if getattr(user, "username", None):
        return "@" + str(user.username)
    full_name = str(getattr(user, "full_name", "") or "").strip()
    if full_name:
        return full_name
    return str(user.id)


def _format_operation_time(value: str | None) -> str:
    if not value:
        return "Unknown time"
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M:%S UTC")
    except ValueError:
        return value


def _build_operation_report(*, payload: dict, actor_label: str, status: str, reply_text: str) -> str:
    source_group = str(payload.get("source_group_title") or "Unknown group").strip()
    original_message = str(payload.get("original_message_text") or "[No message text]").strip()
    destination = str(payload.get("destination") or "Unknown destination").strip()
    source_message_id = payload.get("source_message_id")
    source_ref = source_group
    if source_message_id is not None:
        source_ref = f"{source_group} (message #{source_message_id})"
    agent_label = str(payload.get("agent_label") or "").strip() or (
        f"Agent #{payload['agent_id']}" if payload.get("agent_id") is not None else "Unknown agent"
    )
    timestamp = _format_operation_time(str(payload.get("acted_at") or payload.get("created_at") or ""))
    return "\n".join(
        [
            "Notification Report",
            "",
            f"Status: {status}",
            f"Send confirmed by: {actor_label}",
            f"Agent: {agent_label}",
            f"Destination: {destination}",
            f"Source: {source_ref}",
            f"Time: {timestamp}",
            "",
            "Reply sent:",
            reply_text,
            "",
            "Original message:",
            original_message,
        ]
    )


async def _replace_prompt_with_report(message, *, report_text: str, bot=None) -> None:
    if message is None:
        return
    chat_id = getattr(getattr(message, "chat", None), "id", None)
    try:
        await message.delete()
    except Exception:
        logger.warning("notify_destination_report_delete_failed", chat_id=chat_id)
    sender = bot or getattr(message, "bot", None)
    if sender is None or chat_id is None:
        return
    try:
        await sender.send_message(chat_id=chat_id, text=report_text)
    except Exception:
        logger.warning("notify_destination_report_send_failed", chat_id=chat_id)


def _parse_callback_data(value: str) -> tuple[str, int, str] | None:
    prefix = "notify-destination:"
    if not value.startswith(prefix):
        return None
    parts = value.split(":", 3)
    if len(parts) != 4:
        return None
    action = parts[1]
    group_id_raw = parts[2]
    token = parts[3]
    if action not in {"yes", "no", "edit"}:
        return None
    if not group_id_raw.lstrip("-").isdigit() or not token:
        return None
    return action, int(group_id_raw), token


def _is_command_reply(message: Message) -> bool:
    text = str(message.text or message.caption or "").lstrip()
    if not text.startswith("/"):
        return False
    entities = list(message.entities or []) + list(message.caption_entities or [])
    if not entities:
        return True
    first = entities[0]
    return getattr(first, "offset", None) == 0 and str(getattr(first, "type", "")) == "bot_command"


def _is_reserved_moderation_reply(message: Message) -> bool:
    text = str(message.text or message.caption or "").strip().casefold()
    return text in {item.casefold() for item in _RESERVED_MODERATION_REPLIES}


class NotifyDestinationEditableReplyFilter(Filter):
    async def __call__(self, message: Message) -> bool:
        if message.chat.type not in {"group", "supergroup"}:
            return False
        if getattr(message, "reply_to_message", None) is None or message.from_user is None:
            return False
        return not (_is_command_reply(message) or _is_reserved_moderation_reply(message))


@router.callback_query(F.data.startswith("notify-destination:"))
async def handle_notify_destination_approval(call: CallbackQuery) -> None:
    parsed = _parse_callback_data(str(call.data or ""))
    if parsed is None:
        logger.warning("notify_destination_callback_invalid", data=str(call.data or ""))
        await call.answer("Invalid action.", show_alert=True)
        return
    action, group_id, token = parsed
    logger.info(
        "notify_destination_callback_received",
        action=action,
        group_id=group_id,
        token=token,
        actor_user_id=call.from_user.id if call.from_user else None,
    )

    async with db_session.SessionLocal() as session:
        service = NotifyDestinationApprovalService(session)
        activity_service = TaskActivityService(session)
        payload = await service.get_prompt(group_id=group_id, token=token)
        if payload is None or str(payload.get("status") or "") != "pending":
            logger.warning(
                "notify_destination_callback_missing_or_closed",
                action=action,
                group_id=group_id,
                token=token,
                existing_status=payload.get("status") if payload else None,
            )
            await call.answer("This request is no longer available.", show_alert=True)
            return

        if action == "edit":
            updated = await service.mark_prompt(
                group_id=group_id,
                token=token,
                status="editing",
                acted_by_user_id=call.from_user.id if call.from_user else None,
                acted_by_username=getattr(call.from_user, "username", None) if call.from_user else None,
                acted_by_name=str(getattr(call.from_user, "full_name", "") or "").strip() if call.from_user else None,
            )
            if call.message is not None:
                try:
                    await call.message.edit_text(
                        f"Reply to this message with the custom reply text.\nRequested by {_user_label(call.from_user)}.",
                        reply_markup=None,
                    )
                except Exception:
                    logger.warning("notify_destination_callback_ack_edit_failed", token=token, group_id=group_id)
            logger.info(
                "notify_destination_callback_edit_requested",
                group_id=group_id,
                token=token,
                target_user_id=payload.get("target_user_id"),
                editor_user_id=call.from_user.id if call.from_user else None,
            )
            await call.answer("Send your edited reply as a reply to this message.")
            return

        if action == "yes":
            logger.info(
                "notify_destination_callback_approving",
                group_id=group_id,
                token=token,
                agent_id=payload.get("agent_id"),
                target_user_id=payload.get("target_user_id"),
            )
            agent_id = payload.get("agent_id")
            if agent_id is None:
                await call.answer("Missing agent for this reply.", show_alert=True)
                return
            session_manager = SessionManager(session_factory=db_session.SessionLocal)
            client = await session_manager.get_client(int(agent_id))
            try:
                await UserAgentExecutor().execute(
                    client=client,
                    payload={
                        "group_id": group_id,
                        "chat_id": int(payload["target_user_id"]),
                        "text": str(payload.get("private_reply_text") or ""),
                    },
                )
            finally:
                await client.disconnect()
            updated = await service.mark_prompt(
                group_id=group_id,
                token=token,
                status="approved",
                acted_by_user_id=call.from_user.id if call.from_user else None,
                acted_by_username=getattr(call.from_user, "username", None) if call.from_user else None,
                acted_by_name=str(getattr(call.from_user, "full_name", "") or "").strip() if call.from_user else None,
            )
            if updated is not None:
                await activity_service.log_notify_destination_confirmation(
                    group_id=group_id,
                    target_user_id=int(updated["target_user_id"]),
                    task_key=str(updated.get("task_key") or "notify_destination"),
                    assignment_id=str(updated.get("assignment_id") or ""),
                    token=token,
                    status="approved",
                    confirmed_by_user_id=call.from_user.id if call.from_user else None,
                    confirmed_by_username=getattr(call.from_user, "username", None) if call.from_user else None,
                    confirmed_by_name=str(getattr(call.from_user, "full_name", "") or "").strip() if call.from_user else None,
                    destination=str(updated.get("destination") or ""),
                    agent_id=int(updated["agent_id"]) if updated.get("agent_id") is not None else None,
                )
            await _replace_prompt_with_report(
                call.message,
                report_text=_build_operation_report(
                    payload=updated or payload,
                    actor_label=_user_label(call.from_user),
                    status="Approved",
                    reply_text=str((updated or payload).get("private_reply_text") or ""),
                ),
                bot=call.bot,
            )
            logger.info(
                "notify_destination_callback_approved",
                group_id=group_id,
                token=token,
                target_user_id=payload.get("target_user_id"),
            )
            await call.answer("Reply sent and confirmed.")
            return

        updated = await service.mark_prompt(
            group_id=group_id,
            token=token,
            status="declined",
            acted_by_user_id=call.from_user.id if call.from_user else None,
            acted_by_username=getattr(call.from_user, "username", None) if call.from_user else None,
            acted_by_name=str(getattr(call.from_user, "full_name", "") or "").strip() if call.from_user else None,
        )
        if updated is not None:
            await activity_service.log_notify_destination_confirmation(
                group_id=group_id,
                target_user_id=int(updated["target_user_id"]),
                task_key=str(updated.get("task_key") or "notify_destination"),
                assignment_id=str(updated.get("assignment_id") or ""),
                token=token,
                status="declined",
                confirmed_by_user_id=call.from_user.id if call.from_user else None,
                confirmed_by_username=getattr(call.from_user, "username", None) if call.from_user else None,
                confirmed_by_name=str(getattr(call.from_user, "full_name", "") or "").strip() if call.from_user else None,
                destination=str(updated.get("destination") or ""),
                agent_id=int(updated["agent_id"]) if updated.get("agent_id") is not None else None,
            )
        await _replace_prompt_with_report(
            call.message,
            report_text=_build_operation_report(
                payload=updated or payload,
                actor_label=_user_label(call.from_user),
                status="Declined",
                reply_text=str((updated or payload).get("private_reply_text") or ""),
            ),
            bot=call.bot,
        )
        logger.info(
            "notify_destination_callback_declined",
            group_id=group_id,
            token=token,
            target_user_id=payload.get("target_user_id"),
        )
        await call.answer("Reply skipped and recorded.")


@router.message(NotifyDestinationEditableReplyFilter())
async def handle_notify_destination_edit_reply(message: Message) -> None:
    reply_to = message.reply_to_message
    if reply_to is None or message.from_user is None:
        return
    if _is_command_reply(message) or _is_reserved_moderation_reply(message):
        return
    prompt_message_id = getattr(reply_to, "message_id", None)
    destination = getattr(message.chat, "id", None)
    if prompt_message_id is None or destination is None:
        return
    edited_text = str(message.text or message.caption or "").strip()
    if not edited_text:
        return

    async with db_session.SessionLocal() as session:
        service = NotifyDestinationApprovalService(session)
        activity_service = TaskActivityService(session)
        found = await service.find_prompt_by_control_message(destination=destination, prompt_message_id=int(prompt_message_id))
        if found is None:
            return
        group_id, payload = found
        if str(payload.get("status") or "") not in {"pending", "editing"}:
            return
        agent_id = payload.get("agent_id")
        if agent_id is None:
            await message.reply("Missing agent for this reply.")
            return
        session_manager = SessionManager(session_factory=db_session.SessionLocal)
        client = await session_manager.get_client(int(agent_id))
        try:
            await UserAgentExecutor().execute(
                client=client,
                payload={
                    "group_id": group_id,
                    "chat_id": int(payload["target_user_id"]),
                    "text": edited_text,
                },
            )
        finally:
            await client.disconnect()

        token = str(payload.get("token") or "")
        updated = await service.mark_prompt(
            group_id=group_id,
            token=token,
            status="approved_edited",
            acted_by_user_id=message.from_user.id,
            acted_by_username=getattr(message.from_user, "username", None),
            acted_by_name=str(getattr(message.from_user, "full_name", "") or "").strip(),
        )
        if updated is not None:
            updated["private_reply_text"] = edited_text
            await service.set_prompt(group_id=group_id, token=token, payload=updated)
            await activity_service.log_notify_destination_confirmation(
                group_id=group_id,
                target_user_id=int(updated["target_user_id"]),
                task_key=str(updated.get("task_key") or "notify_destination"),
                assignment_id=str(updated.get("assignment_id") or ""),
                token=token,
                status="approved_edited",
                confirmed_by_user_id=message.from_user.id,
                confirmed_by_username=getattr(message.from_user, "username", None),
                confirmed_by_name=str(getattr(message.from_user, "full_name", "") or "").strip(),
                destination=str(updated.get("destination") or ""),
                agent_id=int(updated["agent_id"]) if updated.get("agent_id") is not None else None,
            )
        await _replace_prompt_with_report(
            reply_to,
            report_text=_build_operation_report(
                payload=updated or payload,
                actor_label=_user_label(message.from_user),
                status="Approved with edited reply",
                reply_text=edited_text,
            ),
            bot=getattr(message, "bot", None),
        )
        await message.reply("Custom reply sent.")
