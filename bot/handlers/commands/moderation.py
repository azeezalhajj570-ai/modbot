from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import ChatPermissions, Message
from sqlalchemy import select

from bot.config import get_settings
from bot.db.models import Group, ModerationLog
from bot.db.session import SessionLocal
from bot.services.group_service import tg_group_id_candidates
from bot.services.moderation_enforcement_service import moderation_incident_count
from bot.utils.i18n import t
from bot.workers.tasks import schedule_bot_message_delete

router = Router(name="moderation_commands")
_BAN_REPLY_ALIASES = {"ban", "/ban", "ban user", "/ban user", "حظر", "/حظر", "حظر المستخدم", "/حظر المستخدم"}
_MUTE_REPLY_ALIASES = {"mute", "/mute", "mute user", "/mute user", "كتم", "/كتم", "كتم المستخدم", "/كتم المستخدم"}


async def _resolve_lang(message: Message) -> str:
    return get_settings().default_language


async def _group_and_lang(message: Message) -> tuple[Group | None, str]:
    lang = await _resolve_lang(message)
    if message.chat.type not in {"group", "supergroup"}:
        return None, lang
    async with SessionLocal() as session:
        group = (
            await session.execute(select(Group).where(Group.tg_group_id.in_(tg_group_id_candidates(message.chat.id))))
        ).scalar_one_or_none()
    return group, lang


async def _is_admin(message: Message) -> bool:
    if message.chat.type not in {"group", "supergroup"} or not message.from_user:
        return False
    member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
    return member.status in {"creator", "administrator", "owner"}


def _reply_target(message: Message) -> int | None:
    reply = getattr(message, "reply_to_message", None)
    from_user = getattr(reply, "from_user", None)
    return getattr(from_user, "id", None)


def _normalized_text(message: Message) -> str:
    return str(message.text or message.caption or "").strip().casefold()


def _reply_moderation_action(message: Message) -> str | None:
    normalized = _normalized_text(message)
    if normalized in {item.casefold() for item in _BAN_REPLY_ALIASES}:
        return "ban"
    if normalized in {item.casefold() for item in _MUTE_REPLY_ALIASES}:
        return "mute"
    return None


def _schedule_command_cleanup(message: Message, *, delay_seconds: int = 60) -> None:
    message_id = getattr(message, "message_id", None)
    chat_id = getattr(getattr(message, "chat", None), "id", None)
    if message_id is None or chat_id is None:
        return
    schedule_bot_message_delete(
        delay_seconds=delay_seconds,
        chat_id=int(chat_id),
        message_id=int(message_id),
    )


async def _handle_unauthorized_moderation_attempt(message: Message, *, group: Group | None, command_name: str) -> None:
    if group is None or message.from_user is None:
        return

    async with SessionLocal() as session:
        session.add(
            ModerationLog(
                group_id=group.id,
                action="unauthorized_moderation_command",
                target_user_id=message.from_user.id,
                admin_user_id=None,
                reason="unauthorized_moderation_command",
                details={"source": "command", "command": command_name},
            )
        )
        await session.flush()

        incident_count = await moderation_incident_count(
            session,
            group_id=group.id,
            user_id=message.from_user.id,
            actions=("unauthorized_moderation_command",),
        )

        action = None
        if incident_count == 5:
            action = "ban"
        elif incident_count == 3:
            action = "mute"

        if action == "mute":
            applied = True
            details: dict[str, object] = {"source": "command", "count": incident_count, "trigger": "unauthorized_moderation_command"}
            try:
                await message.bot.restrict_chat_member(
                    message.chat.id,
                    message.from_user.id,
                    permissions=ChatPermissions(can_send_messages=False),
                )
            except Exception as exc:
                applied = False
                details["error"] = str(exc)
            details["telegram_applied"] = applied
            session.add(
                ModerationLog(
                    group_id=group.id,
                    action="mute_unauthorized_command_user",
                    target_user_id=message.from_user.id,
                    admin_user_id=None,
                    reason="unauthorized_moderation_command",
                    details=details,
                )
            )
        elif action == "ban":
            applied = True
            details = {"source": "command", "count": incident_count, "trigger": "unauthorized_moderation_command"}
            try:
                await message.bot.ban_chat_member(message.chat.id, message.from_user.id)
            except Exception as exc:
                applied = False
                details["error"] = str(exc)
            details["telegram_applied"] = applied
            session.add(
                ModerationLog(
                    group_id=group.id,
                    action="ban_unauthorized_command_user",
                    target_user_id=message.from_user.id,
                    admin_user_id=None,
                    reason="unauthorized_moderation_command",
                    details=details,
                )
            )

        await session.commit()


async def _log_action(
    group: Group | None,
    action: str,
    admin_user_id: int | None,
    target_user_id: int | None,
    details: dict[str, object],
) -> None:
    if not group:
        return
    async with SessionLocal() as session:
        session.add(
            ModerationLog(
                group_id=group.id,
                action=action,
                target_user_id=target_user_id,
                admin_user_id=admin_user_id,
                reason="command_moderation",
                details=details,
            )
        )
        await session.commit()


@router.message(Command("ban"))
async def ban_handler(message: Message) -> None:
    group, lang = await _group_and_lang(message)
    if not await _is_admin(message):
        await _handle_unauthorized_moderation_attempt(message, group=group, command_name="ban")
        await message.answer(t("registergroup_admin_only", lang))
        return
    target_user_id = _reply_target(message)
    if target_user_id is None:
        await message.answer(t("moderation_reply_required", lang))
        return
    await message.bot.ban_chat_member(message.chat.id, target_user_id)
    await _log_action(group, "ban_user", message.from_user.id if message.from_user else None, target_user_id, {"source": "command"})
    await message.answer(t("ban_done", lang))
    _schedule_command_cleanup(message)


@router.message(Command("unban"))
async def unban_handler(message: Message) -> None:
    group, lang = await _group_and_lang(message)
    if not await _is_admin(message):
        await _handle_unauthorized_moderation_attempt(message, group=group, command_name="unban")
        await message.answer(t("registergroup_admin_only", lang))
        return
    target_user_id = _reply_target(message)
    if target_user_id is None:
        await message.answer(t("moderation_reply_required", lang))
        return
    await message.bot.unban_chat_member(message.chat.id, target_user_id)
    await _log_action(group, "unban_user", message.from_user.id if message.from_user else None, target_user_id, {"source": "command"})
    await message.answer(t("unban_done", lang))


@router.message(Command("mute"))
async def mute_handler(message: Message) -> None:
    group, lang = await _group_and_lang(message)
    if not await _is_admin(message):
        await _handle_unauthorized_moderation_attempt(message, group=group, command_name="mute")
        await message.answer(t("registergroup_admin_only", lang))
        return
    target_user_id = _reply_target(message)
    if target_user_id is None:
        await message.answer(t("moderation_reply_required", lang))
        return
    await message.bot.restrict_chat_member(
        message.chat.id,
        target_user_id,
        permissions=ChatPermissions(can_send_messages=False),
    )
    await _log_action(group, "mute_user", message.from_user.id if message.from_user else None, target_user_id, {"source": "command"})
    await message.answer(t("mute_done", lang))
    _schedule_command_cleanup(message)


@router.message(Command("unmute"))
async def unmute_handler(message: Message) -> None:
    group, lang = await _group_and_lang(message)
    if not await _is_admin(message):
        await _handle_unauthorized_moderation_attempt(message, group=group, command_name="unmute")
        await message.answer(t("registergroup_admin_only", lang))
        return
    target_user_id = _reply_target(message)
    if target_user_id is None:
        await message.answer(t("moderation_reply_required", lang))
        return
    await message.bot.restrict_chat_member(
        message.chat.id,
        target_user_id,
        permissions=ChatPermissions(
            can_send_messages=True,
            can_send_audios=True,
            can_send_documents=True,
            can_send_photos=True,
            can_send_videos=True,
            can_send_video_notes=True,
            can_send_voice_notes=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
            can_change_info=False,
            can_invite_users=True,
            can_pin_messages=False,
        ),
    )
    await _log_action(group, "unmute_user", message.from_user.id if message.from_user else None, target_user_id, {"source": "command"})
    await message.answer(t("unmute_done", lang))


@router.message(Command("purge"))
async def purge_handler(message: Message) -> None:
    group, lang = await _group_and_lang(message)
    if not await _is_admin(message):
        await _handle_unauthorized_moderation_attempt(message, group=group, command_name="purge")
        await message.answer(t("registergroup_admin_only", lang))
        return
    parts = (message.text or "").split(maxsplit=1)
    count = 10
    if len(parts) == 2:
        try:
            count = max(1, min(100, int(parts[1])))
        except ValueError:
            await message.answer(t("purge_usage", lang))
            return

    deleted = 0
    start_id = message.message_id
    for current_id in range(start_id, max(0, start_id - count - 1), -1):
        try:
            await message.bot.delete_message(message.chat.id, current_id)
            deleted += 1
        except Exception:
            continue

    await _log_action(
        group,
        "purge_messages",
        message.from_user.id if message.from_user else None,
        None,
        {"source": "command", "count": count, "deleted": deleted},
    )
    await message.answer(t("purge_done", lang, count=deleted))


@router.message(F.chat.type.in_({"group", "supergroup"}), F.reply_to_message)
async def moderation_reply_alias_handler(message: Message) -> None:
    action = _reply_moderation_action(message)
    if action == "ban":
        await ban_handler(message)
    elif action == "mute":
        await mute_handler(message)
