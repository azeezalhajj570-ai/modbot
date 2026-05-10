from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message
import structlog

from bot.agents.dispatch import dispatch_agent_job
from bot.config import get_settings
from bot.core.event_bus import Event, EventBus
from bot.core.runtime.moderation import FlaggedMessageModerationRequest, ModerationRuntimeService
from bot.moderation.service import ModerationService
from redis.asyncio import Redis
from sqlalchemy import select

from bot.db.models import Group, ModerationLog
from bot.db.session import SessionLocal
from bot.monitoring.metrics import MESSAGES_TOTAL
from bot.services.access_gate_service import (
    AccessGateService,
    build_access_gate_buttons,
    build_access_gate_notice,
)
from bot.services.ads_classifier_service import AdsClassifierService
from bot.services.chat_member_service import is_chat_admin
from bot.services.moderation_settings_store import ModerationSettingsStore
from bot.services.settings_service import SettingsService
from bot.services.task_service import TaskService
from bot.utils.rate_limiter import ApiRateLimiter
from bot.summaries.collector import record_group_message_activity
from bot.workers.tasks import run_spam_analysis, schedule_bot_message_delete, schedule_task_follow_up

router = Router(name="moderation_events")
logger = structlog.get_logger(__name__)
settings = get_settings()
ads_service = (
    AdsClassifierService(settings.ads_classifier_url, timeout=settings.ads_classifier_timeout)
    if settings.ads_classifier_url
    else None
)


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


async def _resolve_group(session, tg_group_id: int) -> Group | None:
    candidate_ids = _chat_id_candidates(tg_group_id)
    rows = (
        await session.execute(select(Group).where(Group.tg_group_id.in_(candidate_ids)))
    ).scalars().all()
    if not rows:
        return None
    for group in rows:
        if group.tg_group_id == tg_group_id:
            return group
    return rows[0]


async def _setting_enabled(session, group_id: int, key: str, default: bool = True) -> bool:
    return await ModerationSettingsStore(session).is_feature_enabled(group_id, key, default=default)


def _message_lang(message: Message) -> str:
    _ = message
    return settings.default_language


def _is_bot_command_message(message: Message) -> bool:
    text = str(message.text or message.caption or "").lstrip()
    if not text.startswith("/"):
        return False
    entities = list(message.entities or []) + list(message.caption_entities or [])
    if not entities:
        return True
    first = entities[0]
    return getattr(first, "offset", None) == 0 and str(getattr(first, "type", "")) == "bot_command"


async def _required_group_titles(session, required_group_tg_ids: list[int]) -> list[str]:
    title_map: dict[int, str] = {}
    for required_group_tg_id in required_group_tg_ids:
        candidates = _chat_id_candidates(required_group_tg_id)
        rows = (
            await session.execute(select(Group.tg_group_id, Group.title).where(Group.tg_group_id.in_(candidates)))
        ).all()
        for row in rows:
            title_map[int(row.tg_group_id)] = str(row.title)
        for candidate_id in candidates:
            if candidate_id in title_map:
                break
        else:
            title_map[required_group_tg_id] = str(required_group_tg_id)

    titles: list[str] = []
    for required_group_tg_id in required_group_tg_ids:
        for candidate_id in _chat_id_candidates(required_group_tg_id):
            title = title_map.get(candidate_id)
            if title:
                titles.append(title)
                break
    return titles


async def _required_group_targets(session, bot, required_group_tg_ids: list[int]) -> list[tuple[str, str]]:
    rows = (
        await session.execute(
            select(Group.tg_group_id, Group.title).where(Group.tg_group_id.in_(set(
                candidate_id
                for required_group_tg_id in required_group_tg_ids
                for candidate_id in _chat_id_candidates(required_group_tg_id)
            )))
        )
    ).all()
    title_map = {int(row.tg_group_id): str(row.title) for row in rows}

    targets: list[tuple[str, str]] = []
    for required_group_tg_id in required_group_tg_ids:
        title = next(
            (title_map[candidate_id] for candidate_id in _chat_id_candidates(required_group_tg_id) if candidate_id in title_map),
            str(required_group_tg_id),
        )
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


async def _missing_required_group_tg_ids(
    bot,
    group_tg_id: int,
    user_id: int,
    required_group_tg_ids: list[int],
) -> list[int]:
    missing_required_groups: list[int] = []
    for req_tg_group_id in required_group_tg_ids:
        is_member = False
        for candidate_req_tg_group_id in _chat_id_candidates(req_tg_group_id):
            try:
                member = await bot.get_chat_member(candidate_req_tg_group_id, user_id)
                if _is_group_member(member):
                    is_member = True
                    break
            except Exception:
                logger.debug(
                    "access_gate_member_check_failed",
                    group_tg_id=group_tg_id,
                    user_id=user_id,
                    required_group_tg_id=req_tg_group_id,
                    candidate_required_group_tg_id=candidate_req_tg_group_id,
                )
                continue
        if not is_member:
            missing_required_groups.append(req_tg_group_id)
    return missing_required_groups


def _message_contains_link(message: Message, text: str) -> bool:
    if text and ("http://" in text.lower() or "https://" in text.lower() or "www." in text.lower() or "t.me/" in text.lower()):
        return True

    entities = list(message.entities or []) + list(message.caption_entities or [])
    for entity in entities:
        entity_type = str(getattr(entity, "type", "")).lower()
        if entity_type in {"url", "text_link"}:
            return True
    return False


def _message_trace_payload(message: Message, text: str, contains_link: bool) -> dict[str, object]:
    return {
        "chat_id": message.chat.id,
        "chat_type": message.chat.type,
        "user_id": message.from_user.id if message.from_user else None,
        "message_id": message.message_id,
        "text": text,
        "has_text": bool(text),
        "contains_link": contains_link,
        "entity_types": [str(getattr(entity, "type", "")) for entity in message.entities or []],
        "caption_entity_types": [str(getattr(entity, "type", "")) for entity in message.caption_entities or []],
    }


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def on_group_message(message: Message, event_bus: EventBus, redis: Redis | None = None) -> None:
    if _is_bot_command_message(message):
        return
    MESSAGES_TOTAL.labels(chat_type=message.chat.type).inc()
    text = (message.text or message.caption or "").strip()
    contains_link = _message_contains_link(message, text)
    user_id = message.from_user.id if message.from_user else None
    group: Group | None = None
    logger.info(
        "moderation_group_message_received",
        chat_id=message.chat.id,
        chat_type=message.chat.type,
        user_id=user_id,
        message_id=message.message_id,
        has_text=bool(text),
    )
    logger.info("moderation_message_trace", **_message_trace_payload(message, text, contains_link))

    sender_is_admin = False
    if user_id:
        try:
            sender_is_admin = await is_chat_admin(message.bot, message.chat.id, user_id)
        except Exception:
            logger.warning(
                "moderation_admin_check_failed",
                chat_id=message.chat.id,
                user_id=user_id,
                message_id=message.message_id,
            )

    if user_id and not sender_is_admin and redis:
        limit_key = f"ratelimit:msg:{message.chat.id}:{user_id}"
        now = int((await redis.time())[0])
        window_start = now - 60
        async with redis.pipeline() as pipe:
            pipe.zremrangebyscore(limit_key, 0, window_start)
            pipe.zcard(limit_key)
            pipe.zadd(limit_key, {str(message.message_id): now})
            pipe.expire(limit_key, 65)
            _, current_count, _, _ = await pipe.execute()
        async with SessionLocal() as session:
            group = group or await _resolve_group(session, message.chat.id)
            if group:
                gs = await SettingsService(session).get_all(group.id)
                max_per_min = int(gs.get("max_messages_per_minute", 0))
                if max_per_min > 0 and int(current_count) > max_per_min:
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    logger.info(
                        "rate_limit_message_deleted",
                        chat_id=message.chat.id,
                        user_id=user_id,
                        message_id=message.message_id,
                        count=current_count,
                        limit=max_per_min,
                    )
                    return

    if user_id:
        async with SessionLocal() as session:
            # AI Moderation Service Call
            mod_service = ModerationService(session, redis_client=redis, bot=message.bot)
            await mod_service.process_message(
                chat_id=message.chat.id,
                message_id=message.message_id,
                user_id=user_id,
                username=message.from_user.username if message.from_user else None,
                text=text,
                context_overrides={"is_admin": sender_is_admin},
            )

            group = await _resolve_group(session, message.chat.id)
            if group:
                await record_group_message_activity(session, group=group, message=message)
                required_groups = await AccessGateService(session).list_required_group_tg_ids(group.id)
                if required_groups:
                    missing_required_groups = await _missing_required_group_tg_ids(
                        message.bot,
                        message.chat.id,
                        user_id,
                        required_groups,
                    )

                    if missing_required_groups:
                        required_group_titles = await _required_group_titles(session, missing_required_groups)
                        required_group_targets = await _required_group_targets(session, message.bot, missing_required_groups)
                        try:
                            await message.delete()
                            logger.info(
                                "access_gate_message_deleted",
                                group_id=group.id,
                                group_tg_id=message.chat.id,
                                user_id=user_id,
                                required_groups=required_groups,
                                missing_required_groups=missing_required_groups,
                            )
                        except Exception:
                            logger.warning(
                                "access_gate_delete_failed",
                                group_id=group.id,
                                group_tg_id=message.chat.id,
                                user_id=user_id,
                            )
                        try:
                            await message.answer(
                                build_access_gate_notice(_message_lang(message), required_group_titles),
                                reply_markup=build_access_gate_buttons(required_group_targets),
                            )
                        except Exception:
                            logger.warning(
                                "access_gate_notice_failed",
                                group_id=group.id,
                                group_tg_id=message.chat.id,
                                user_id=user_id,
                            )
                        session.add(
                            ModerationLog(
                                group_id=group.id,
                                action="delete_not_in_required_groups",
                                target_user_id=user_id,
                                admin_user_id=None,
                                reason="access_gate",
                                details={
                                    "required_groups": required_groups,
                                    "missing_required_groups": missing_required_groups,
                                },
                            )
                        )
                        await session.commit()
                        return
                    logger.info(
                        "access_gate_member_allowed",
                        group_id=group.id,
                        group_tg_id=message.chat.id,
                        user_id=user_id,
                        required_groups=required_groups,
                    )

    anti_ads_enabled = True
    anti_spam_enabled = True
    if group:
        async with SessionLocal() as session:
            anti_ads_enabled = await _setting_enabled(session, group.id, "anti_ads")
            anti_spam_enabled = await _setting_enabled(session, group.id, "anti_spam")

    if ads_service and text and anti_ads_enabled:
        result = await ads_service.classify(text)
        if result and result.label == "ad" and result.ad_score >= settings.ads_classifier_threshold and not sender_is_admin:
            async with SessionLocal() as session:
                group = group or await _resolve_group(session, message.chat.id)
                if group:
                    await ModerationRuntimeService(session).enforce_flagged_message(
                        FlaggedMessageModerationRequest(
                            group_id=group.id,
                            chat_id=message.chat.id,
                            message_id=message.message_id,
                            target_user_id=message.from_user.id if message.from_user else None,
                            source="anti_ads",
                            reason="ads_classifier",
                            score=result.ad_score,
                            notice_key="anti_ads",
                            feature_key="anti_ads",
                            delete_log_action="delete_ad",
                            mute_setting_key="anti_ads_mute",
                            mute_threshold_key="anti_ads_mute_limit",
                            mute_log_action="mute_ad_user",
                            incident_actions=("delete_ad",),
                            target_is_admin=sender_is_admin,
                            lang=_message_lang(message),
                            metadata={"ad_score": result.ad_score, "message_id": message.message_id},
                        ),
                        bot=message.bot,
                    )
            return

    if text or contains_link:
        async with SessionLocal() as session:
            group = group or await _resolve_group(session, message.chat.id)
            if group:
                await TaskService(
                    session,
                    dispatch_agent_job=dispatch_agent_job,
                    dispatch_follow_up=schedule_task_follow_up,
                    dispatch_delete_message=schedule_bot_message_delete,
                    rate_limiter=ApiRateLimiter(redis) if redis else None,
                    rate_limit_per_group_minute=settings.automation_rate_limit_per_group_minute,
                    ).handle_message_event(
                        group_id=group.id,
                        user_id=message.from_user.id if message.from_user else None,
                        payload={
                            "chat_id": message.chat.id,
                            "group_title": group.title or getattr(message.chat, "title", ""),
                            "text": text,
                            "message_id": message.message_id,
                            "first_name": getattr(message.from_user, "first_name", "") if message.from_user else "",
                            "full_name": getattr(message.from_user, "full_name", "") if message.from_user else "",
                            "username": getattr(message.from_user, "username", "") if message.from_user else "",
                            "bot": message.bot,
                            "contains_link": contains_link,
                            "lang": _message_lang(message),
                        },
                    )

        logger.info(
            "moderation_message_publish",
            chat_id=message.chat.id,
            chat_type=message.chat.type,
            user_id=message.from_user.id if message.from_user else None,
            message_id=message.message_id,
            contains_link=contains_link,
            text=text,
        )
        await event_bus.publish(
            Event(
                name="MessageReceived",
                group_id=message.chat.id,
                user_id=message.from_user.id if message.from_user else None,
                payload={
                    "text": text,
                    "message_id": message.message_id,
                    "bot": message.bot,
                    "contains_link": contains_link,
                    "lang": _message_lang(message),
                },
            )
        )

        if anti_spam_enabled and text:
            run_spam_analysis.send(
                message.chat.id,
                message.message_id,
                message.from_user.id if message.from_user else 0,
                text,
                _message_lang(message),
            )


@router.message(F.chat.type.in_({"group", "supergroup"}), F.new_chat_members)
async def on_new_chat_members(message: Message) -> None:
    members = list(message.new_chat_members or [])
    if not members:
        return

    async with SessionLocal() as session:
        group = await _resolve_group(session, message.chat.id)
        if not group:
            return
        service = TaskService(
            session,
            dispatch_agent_job=dispatch_agent_job,
            dispatch_follow_up=schedule_task_follow_up,
            dispatch_delete_message=schedule_bot_message_delete,
        )
        for member in members:
            if getattr(member, "is_bot", False):
                continue
            await service.handle_member_join_event(
                group_id=group.id,
                user_id=getattr(member, "id", None),
                payload={
                    "chat_id": message.chat.id,
                    "message_id": message.message_id,
                    "bot": message.bot,
                    "first_name": getattr(member, "first_name", ""),
                    "full_name": getattr(member, "full_name", getattr(member, "first_name", "")),
                },
            )
