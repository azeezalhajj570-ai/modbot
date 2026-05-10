"""Telethon-based agent execution runtime."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

from aiogram import Bot
import structlog
from sqlalchemy import select

from bot.agents.exceptions import AgentBannedError, AgentFloodWaitError
from bot.agents.jobs import (
    ADD_CONTACT_JOB_TYPE,
    GROUP_MEMBER_BROADCAST_JOB_TYPE,
    SCRAPER_FULL_GROUP_JOB_TYPE,
    SCRAPER_GROUP_INFO_JOB_TYPE,
    SCRAPER_MEMBERS_JOB_TYPE,
    SCRAPER_MESSAGES_JOB_TYPE,
    normalize_group_member_broadcast_payload,
)
from bot.automation.agent_task_store import AgentTaskStore
from bot.automation.models import TaskEvent
from bot.automation.registry import Registry
from bot.config import get_settings
from bot.db.models import Agent, AgentJob, ScrapedMember
from bot.db.session import SessionLocal
from bot.utils.rate_limiter import AgentRateLimiter
from bot.services.notify_destination_approval_service import NotifyDestinationApprovalService
from bot.services.task_activity_service import TaskActivityService

__all__ = [
    "ADD_CONTACT_JOB_TYPE",
    "GROUP_MEMBER_BROADCAST_JOB_TYPE",
    "SCRAPER_FULL_GROUP_JOB_TYPE",
    "SCRAPER_GROUP_INFO_JOB_TYPE",
    "SCRAPER_MEMBERS_JOB_TYPE",
    "SCRAPER_MESSAGES_JOB_TYPE",
    "AddContactRuntime",
    "GroupMemberBroadcastRuntime",
    "ScraperRuntime",
    "UserAgentExecutor",
]

logger = structlog.get_logger(__name__)


def _translate_client_exception(exc: Exception) -> Exception | None:
    try:
        from telethon.errors import FloodWaitError
        from telethon.errors.rpcerrorlist import PhoneNumberBannedError, UserDeactivatedBanError

        if isinstance(exc, FloodWaitError):
            return AgentFloodWaitError(retry_after=exc.seconds)
        if isinstance(exc, (PhoneNumberBannedError, UserDeactivatedBanError)):
            return AgentBannedError()
    except ImportError:
        pass
    return None


class UserAgentExecutor:
    def __init__(self, *, bot: Bot | None = None) -> None:
        self.bot = bot

    async def execute(self, *, client, payload: dict[str, Any]) -> bool:
        chat_id = payload.get("chat_id") or payload.get("group_id")
        text = payload.get("text", "")
        if not chat_id or not text:
            return False
        try:
            await client.send_message(int(chat_id), str(text))
            return True
        except Exception:
            return False

    async def run(self, *, agent: Agent, job: AgentJob, registry: Registry, session: Any) -> bool:
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        settings = get_settings()
        if not settings.telegram_api_id or not settings.telegram_api_hash:
            return False

        managed_client = TelegramClient(StringSession(agent.session_string), settings.telegram_api_id, settings.telegram_api_hash)
        await managed_client.connect()
        try:
            task_store = AgentTaskStore(session)
            activity_service = TaskActivityService(session)
            approval_service = NotifyDestinationApprovalService(session)
            runtime = AgentTaskRuntime(
                registry=registry,
                task_store=task_store,
                activity_service=activity_service,
                approval_service=approval_service,
            )
            return await runtime.execute(client=managed_client, agent=agent, job=job, session=session)
        finally:
            await managed_client.disconnect()


class AddContactRuntime:
    async def resolve_group_entity(self, client, tg_group_id: int) -> Any:
        from bot.services.group_service import canonical_tg_group_id
        from bot.db.models import ScrapedGroup
        from telethon.tl.types import InputPeerChannel, InputPeerChat
        
        canonical_id = canonical_tg_group_id(tg_group_id)
        try:
            return await client.get_entity(tg_group_id)
        except Exception:
            async with SessionLocal() as session:
                stmt = select(ScrapedGroup).where(ScrapedGroup.tg_group_id == canonical_id).limit(1)
                group_record = (await session.execute(stmt)).scalar_one_or_none()
                if group_record and group_record.raw_data:
                    g_access_hash = group_record.raw_data.get("access_hash")
                    if g_access_hash:
                        if group_record.group_type in {"channel", "supergroup"}:
                            return await client.get_entity(InputPeerChannel(channel_id=abs(canonical_id) % (10**10) if canonical_id < -10**12 else abs(canonical_id), access_hash=int(g_access_hash)))
                        else:
                            return await client.get_entity(InputPeerChat(chat_id=abs(canonical_id)))
            raise

    async def execute(self, *, client, agent: Agent, payload: dict[str, Any]) -> dict[str, Any]:
        user_id = payload.get("user_id")
        if not user_id:
            raise ValueError("user_id is required to add contact")
            
        user_id_int = int(user_id)
        if user_id_int < 0:
             raise ValueError(f"Invalid user_id {user_id}: Cannot add a group or channel as a contact.")

        username = payload.get("username")
        tg_group_id = payload.get("tg_group_id")
        group_title = str(payload.get("group_title") or "Group").strip()
        
        # Implementation of naming convention: [Suffix] [GroupID] [GroupName] - [Name]
        agent_phone = str(agent.phone_number or "NoPhone").strip()
        phone_suffix = agent_phone[-4:] if len(agent_phone) >= 4 else agent_phone

        raw_first_name = str(payload.get("first_name") or "User").strip()
        raw_last_name = str(payload.get("last_name") or "").strip()

        # Build prefix components
        prefix_parts = [phone_suffix]
        if tg_group_id:
            prefix_parts.append(str(tg_group_id))
        if group_title and group_title != "Group":
            prefix_parts.append(group_title)

        first_name = f"{' '.join(prefix_parts)} -"
        last_name = f"{raw_first_name} {raw_last_name}".strip()

        # Prime the cache to avoid "Could not find the input entity"
        target_peer = None
        
        # 1. Try by username
        if username:
            try:
                target_peer = await client.get_input_entity(str(username))
            except Exception:
                logger.warning("add_contact_prime_username_failed", username=username)

        # 2. Try database-backed access hash (Persistent fallback)
        if target_peer is None:
            from telethon.tl.types import InputPeerUser
            async with SessionLocal() as session:
                # Prefer records with access_hash
                stmt = select(ScrapedMember).where(ScrapedMember.tg_user_id == user_id_int).order_by(ScrapedMember.scraped_at.desc())
                results = (await session.execute(stmt)).scalars().all()
                member_record = next((r for r in results if r.raw_data.get("access_hash")), None)
                if not member_record and results:
                    member_record = results[0]

                if member_record and member_record.raw_data:
                    access_hash = member_record.raw_data.get("access_hash")
                    if access_hash:
                        target_peer = InputPeerUser(user_id=user_id_int, access_hash=int(access_hash))

        # 3. Try official group fetching (Chat context priming)
        if target_peer is None and tg_group_id:
            try:
                group_entity = await self.resolve_group_entity(client, int(tg_group_id))
                if group_entity:
                    # Search for the user in this group to prime the cache
                    async for u in client.iter_participants(group_entity, search=str(user_id_int)):
                        if u.id == user_id_int:
                            target_peer = await client.get_input_entity(u)
                            break
            except Exception as exc:
                logger.warning("add_contact_prime_group_failed", user_id=user_id_int, tg_group_id=tg_group_id, error=str(exc))

        # 4. Fallback to direct resolution
        if target_peer is None:
            try:
                target_peer = await client.get_input_entity(user_id_int)
            except Exception:
                # Absolute last resort: try a global entity fetch
                try:
                    target_peer = await client.get_entity(user_id_int)
                except Exception:
                    raise ValueError(
                        f"Could not resolve user {user_id_int}. Try syncing the workspace or scraping again."
                    )

        from telethon.tl.types import InputPeerUser, InputUser, InputPeerSelf
        from telethon.tl.functions.contacts import AddContactRequest

        # Final type safety check: only users can be added as contacts
        is_user = isinstance(target_peer, (InputPeerUser, InputUser, InputPeerSelf)) or (isinstance(target_peer, int) and target_peer > 0)
        if not is_user:
             raise ValueError(f"Entity {user_id_int} is not a valid Telegram user and cannot be added to contacts.")

        try:
            await client(
                AddContactRequest(
                    id=target_peer,
                    first_name=first_name,
                    last_name=last_name,
                    phone=str(payload.get("phone") or "").strip(),
                    add_phone_privacy_exception=True,
                )
            )
            return {
                "user_id": user_id_int,
                "first_name": first_name,
                "last_name": last_name,
                "success": True,
            }
        except Exception as exc:
            translated = _translate_client_exception(exc)
            if translated is not None:
                raise translated from exc
            raise


class GroupMemberBroadcastRuntime:
    def __init__(self, *, sleep=asyncio.sleep) -> None:
        self.sleep = sleep

    async def execute(self, *, client, agent: Agent, payload: dict[str, Any]) -> dict[str, Any]:
        import random
        from bot.config import get_settings
        from bot.utils.rate_limiter import AgentRateLimiter
        from redis.asyncio import Redis

        normalized = normalize_group_member_broadcast_payload(payload)

        redis_client = Redis.from_url(get_settings().redis_url, decode_responses=True)
        limiter = AgentRateLimiter(redis_client)
        try:
            message = normalized["message"]
            threshold = int(normalized.get("threshold") or 0)
            base_interval = float(normalized.get("interval_seconds") or 2.0)
            selected_user_ids = {int(uid) for uid in normalized.get("selected_user_ids", [])}

            progress = dict(payload.get("progress") or {})
            already_sent: set[int] = set(int(uid) for uid in progress.get("sent_users", []))
            skipped_count = len(already_sent)
            success_count = progress.get("success_count", 0)
            failure_count = progress.get("failure_count", 0)
            failures: list[dict[str, Any]] = list(progress.get("failures", []))

            source_group_id = int(normalized["source_group_id"])
            group_entity = await AddContactRuntime().resolve_group_entity(client, source_group_id)
            recipients: list[int] = []
            async for participant in client.iter_participants(group_entity):
                pid = getattr(participant, "id", None)
                if pid is None:
                    continue
                if bool(normalized.get("skip_bots", True)) and bool(getattr(participant, "bot", False)):
                    continue
                if bool(getattr(participant, "deleted", False)):
                    continue
                if agent.telegram_user_id is not None and int(pid) == int(agent.telegram_user_id):
                    continue
                if selected_user_ids and int(pid) not in selected_user_ids:
                    continue
                recipients.append(int(pid))

            recipients_set = set(recipients)
            recipients = [r for r in recipients if r not in already_sent]
            total_count = len(recipients_set)
            remaining = recipients[:threshold] if threshold > 0 else recipients
            payload["progress"] = {
                "total_count": total_count,
                "success_count": success_count,
                "failure_count": failure_count,
                "skipped_count": skipped_count,
                "sent_users": list(already_sent),
                "failures": failures,
            }

            for index, recipient_id in enumerate(remaining):
                cooldown_mins = getattr(agent, "cooldown_minutes", None)
                if cooldown_mins is not None and cooldown_mins > 0:
                    in_cooldown, cd_remaining = await limiter.is_in_cooldown(agent.id, cooldown_mins)
                    if in_cooldown:
                        payload["progress"]["stopped_at"] = index
                        payload["progress"]["stop_reason"] = "cooldown"
                        payload["progress"]["retry_after"] = int(cd_remaining)
                        raise _translate_client_exception(Exception(f"Agent cooldown: {cd_remaining}s")) or Exception(f"Cooldown: {cd_remaining}s")

                max_per_hour = getattr(agent, "max_actions_per_hour", None)
                if max_per_hour is not None and max_per_hour > 0:
                    allowed, hour_count = await limiter.check_and_increment(agent.id, max_per_hour)
                    if not allowed:
                        payload["progress"]["stopped_at"] = index
                        payload["progress"]["stop_reason"] = "hourly_limit"
                        raise Exception(f"Hourly limit reached ({hour_count}/{max_per_hour})")

                max_per_day = getattr(agent, "max_messages_per_day", None) or 500
                if max_per_day > 0:
                    allowed, day_count = await limiter.check_daily_limit(agent.id, max_per_day)
                    if not allowed:
                        payload["progress"]["stopped_at"] = index
                        payload["progress"]["stop_reason"] = "daily_limit"
                        raise Exception(f"Daily limit reached ({day_count}/{max_per_day})")

                min_delay = getattr(agent, "min_delay_seconds", None)
                if min_delay is not None and min_delay > 0:
                    wait = await limiter.enforce_delay(agent.id, float(min_delay))
                    if wait > 0:
                        await self.sleep(wait)

                try:
                    await client.send_message(recipient_id, message)
                    success_count += 1
                    already_sent.add(recipient_id)
                    await limiter.record_send(agent.id)
                except Exception as exc:
                    failure_count += 1
                    translated = _translate_client_exception(exc)
                    if translated is not None:
                        payload["progress"]["stopped_at"] = index
                        payload["progress"]["stop_reason"] = type(translated).__name__
                        payload["progress"]["sent_users"] = list(already_sent)
                        payload["progress"]["success_count"] = success_count
                        payload["progress"]["failure_count"] = failure_count
                        raise translated from exc
                    failures.append({"user_id": str(recipient_id), "error": str(exc)[:200]})

                effective_interval = base_interval
                if base_interval > 0:
                    jitter = random.uniform(-0.3, 0.3) * base_interval
                    effective_interval = max(0.3, base_interval + jitter)
                if index < len(remaining) - 1 and effective_interval > 0:
                    await self.sleep(effective_interval)

            return {
                "success_count": success_count,
                "failure_count": failure_count,
                "total_count": total_count,
                "skipped_already_sent": skipped_count,
                "failures": failures,
                "_progress": dict(payload.get("progress") or {}),
            }
        finally:
            await redis_client.aclose()


class ScraperRuntime:
    async def execute(self, *, client, agent: Agent, payload: dict[str, Any], job_type: str | None = None) -> dict[str, Any]:
        from bot.services.scraper_service import ScraperService

        async with SessionLocal() as session:
            service = ScraperService(session)
            active_job_type = job_type or payload.get("job_type") or payload.get("type")
            tg_group_id = payload.get("tg_group_id")
            if not tg_group_id:
                raise ValueError("tg_group_id is required for scraper jobs")

            if active_job_type == SCRAPER_GROUP_INFO_JOB_TYPE:
                result = await service._scrape_group_info_dict(agent_id=agent.id, tg_group_id=int(tg_group_id), client=client)
                return {
                    "job_type": active_job_type,
                    "tg_group_id": int(tg_group_id),
                    "success": result is not None,
                    "group_info": result,
                }
            elif active_job_type == SCRAPER_MEMBERS_JOB_TYPE:
                result = await service.scrape_members(
                    agent_id=agent.id,
                    tg_group_id=int(tg_group_id),
                    limit=int(payload.get("limit", payload.get("member_limit", 1000))),
                    client=client,
                )
                return {
                    "job_type": active_job_type,
                    "tg_group_id": int(tg_group_id),
                    **result,
                }
            elif active_job_type == SCRAPER_MESSAGES_JOB_TYPE:
                scan_strategy = payload.get("scan_strategy", "auto")
                max_age_days = int(payload.get("max_age_days", 30)) if payload.get("max_age_days") else None

                if scan_strategy == "checkpoint":
                    result = await service.scrape_messages_checkpointed(
                        agent_id=agent.id,
                        tg_group_id=int(tg_group_id),
                        limit=int(payload.get("limit", payload.get("message_limit", 100))),
                        max_age_days=max_age_days,
                        client=client,
                    )
                elif scan_strategy == "two_period":
                    recent_days = int(payload.get("recent_days", 30))
                    archive_days = int(payload.get("archive_days", 365))
                    result = await service.scrape_messages_two_period(
                        agent_id=agent.id,
                        tg_group_id=int(tg_group_id),
                        recent_days=recent_days,
                        archive_days=archive_days,
                        client=client,
                    )
                else:
                    result = await service.scrape_messages(
                        agent_id=agent.id,
                        tg_group_id=int(tg_group_id),
                        limit=int(payload.get("limit", payload.get("message_limit", 100))),
                        max_age_days=max_age_days,
                        client=client,
                    )
                return {
                    "job_type": active_job_type,
                    "tg_group_id": int(tg_group_id),
                    **result,
                }
            elif active_job_type == SCRAPER_FULL_GROUP_JOB_TYPE:
                scrape_members = payload.get("scrape_members", True)
                scrape_messages = payload.get("scrape_messages", True)
                max_age_days = int(payload.get("max_age_days", 30)) if payload.get("max_age_days") else None
                scan_strategy = payload.get("scan_strategy", "auto")
                result = await service.scrape_full_group(
                    agent_id=agent.id,
                    tg_group_id=int(tg_group_id),
                    scrape_members=bool(scrape_members),
                    scrape_messages=bool(scrape_messages),
                    member_limit=int(payload.get("member_limit", 1000)),
                    message_limit=int(payload.get("message_limit", 100)),
                    max_age_days=max_age_days,
                    scan_strategy=scan_strategy,
                    client=client,
                )
                return {
                    "job_type": active_job_type,
                    "tg_group_id": int(tg_group_id),
                    "group_info": result.get("group_info"),
                    "members": result["members"],
                    "messages": result["messages"],
                }
            else:
                raise ValueError(f"Unsupported scraper job type: {active_job_type}")


class AgentTaskRuntime:
    def __init__(
        self,
        *,
        registry: Registry,
        task_store: AgentTaskStore | None = None,
        activity_service: TaskActivityService | None = None,
        approval_service: NotifyDestinationApprovalService | None = None,
    ) -> None:
        self.registry = registry
        self.task_store = task_store
        self.activity_service = activity_service
        self.approval_service = approval_service

    async def execute(self, *, client, agent: Agent, job: AgentJob, session: Any) -> bool:
        payload = dict(job.job_payload or {})
        task_key = payload.get("task_key")
        assignment_id = payload.get("assignment_id")
        event_data = payload.get("event", {})
        event_payload = event_data.get("payload", {})
        task_config = payload.get("task_config", {})

        if not task_key or not assignment_id:
            return False

        definition = self.registry.get(task_key)
        if not definition:
            return False

        try:
            event = TaskEvent(
                name=event_data.get("name") or task_key,
                group_id=event_data.get("group_id", 0),
                user_id=event_data.get("user_id"),
                payload=event_payload,
            )

            from redis.asyncio import Redis
            redis_client = Redis.from_url(get_settings().redis_url, decode_responses=True)
            limiter = AgentRateLimiter(redis_client)

            try:
                cooldown_mins = getattr(agent, "cooldown_minutes", None)
                if cooldown_mins is not None and cooldown_mins > 0:
                    in_cooldown, remaining = await limiter.is_in_cooldown(agent.id, cooldown_mins)
                    if in_cooldown:
                        logger.warning("agent_in_cooldown", agent_id=agent.id, remaining_seconds=remaining)
                        return False

                safety_enabled = getattr(agent, "safety_mode_enabled", True)
                safety_until = getattr(agent, "safety_mode_until", None)
                if await limiter.check_safety_mode(agent.id, safety_enabled, safety_until):
                    logger.info("agent_in_safety_mode", agent_id=agent.id, safety_until=safety_until)
                    result = await definition.handler(task_config, event)
                    if isinstance(result, dict):
                        result["_safety_mode"] = True
                    return True

                max_per_hour = (
                    task_config.get("max_actions_per_hour")
                    or payload.get("max_actions_per_hour")
                    or getattr(agent, "max_actions_per_hour", None)
                )
                if max_per_hour is not None:
                    allowed, count = await limiter.check_and_increment(agent.id, int(max_per_hour))
                    if not allowed:
                        logger.warning("agent_rate_limit_exceeded", agent_id=agent.id, limit=max_per_hour, count=count)
                        cooldown_mins = getattr(agent, "cooldown_minutes", None)
                        if cooldown_mins is not None and cooldown_mins > 0:
                            await limiter.start_cooldown(agent.id, cooldown_mins)
                            logger.warning("agent_entered_cooldown", agent_id=agent.id, cooldown_minutes=cooldown_mins)
                        return False

                min_delay = (
                    task_config.get("min_delay_seconds")
                    or payload.get("min_delay_seconds")
                    or getattr(agent, "min_delay_seconds", None)
                )
                if min_delay is not None:
                    wait_seconds = await limiter.enforce_delay(agent.id, float(min_delay))
                    if wait_seconds > 0:
                        import asyncio
                        await asyncio.sleep(wait_seconds)

            finally:
                await redis_client.aclose()

            # Handle Approval Requests if present in payload
            approval_request = payload.get("approval_request")
            if isinstance(approval_request, dict):
                target_user_id = approval_request.get("target_user_id")
                if target_user_id is None:
                    raise ValueError("Approval requests require target_user_id")
                
                group_id = event_payload.get("group_id")
                destination = approval_request.get("chat_id") or group_id
                
                if self.approval_service and group_id:
                    bot = Bot(token=get_settings().bot_token)
                    try:
                        await self.approval_service.create_prompt(
                            group_id=int(group_id),
                            assignment_id=str(assignment_id),
                            task_key=str(task_key),
                            agent_id=agent.id,
                            destination=destination,
                            prompt_text=str(approval_request.get("prompt_text") or "").strip(),
                            private_reply_text=str(approval_request.get("private_reply_text") or "").strip(),
                            target_user_id=int(target_user_id),
                            source_group_title=str(approval_request.get("source_group_title") or "").strip(),
                            original_message_text=str(approval_request.get("original_message_text") or "").strip(),
                            source_chat_id=approval_request.get("source_chat_id"),
                            source_message_id=approval_request.get("source_message_id"),
                            bot=bot,
                        )
                    finally:
                        await bot.session.close()

            result = await definition.handler(task_config, event)
            if not isinstance(result, dict):
                return True

            if task_key == "lead_capture":
                await self._capture_lead(agent=agent, session=session, event=event, result=result)

            chat_id = result.get("chat_id") or event.payload.get("chat_id") or event.group_id
            text = result.get("text", "")
            if text:
                reply_to = result.get("reply_to_message_id")
                kwargs = {}
                if reply_to:
                    kwargs["reply_to"] = reply_to
                sent = None
                if result.get("_safety_mode"):
                    sent = await client.send_message(chat_id, text, **kwargs)
                    logger.info("safety_mode_action_executed", agent_id=agent.id, task_key=task_key)
                else:
                    sent = await client.send_message(chat_id, text, **kwargs)

                delete_after = result.get("delete_after_seconds", 0)
                if delete_after > 0 and sent is not None:
                    bot_message_id = sent.id
                    async def _delete_later():
                        await asyncio.sleep(delete_after)
                        try:
                            await client.delete_messages(chat_id, [bot_message_id])
                        except Exception:
                            pass
                    asyncio.ensure_future(_delete_later())

            if self.activity_service and assignment_id:
                await self.activity_service.record_activity(
                    assignment_id=str(assignment_id),
                    status="success",
                )

            return True
        except Exception as exc:
            logger.exception("agent_task_execution_failed", task_key=task_key, assignment_id=assignment_id)
            if self.activity_service and assignment_id:
                await self.activity_service.record_activity(
                    assignment_id=str(assignment_id),
                    status="failed",
                    error=str(exc),
                )
            raise

    async def _capture_lead(
        self, *, agent, session, event: "TaskEvent", result: dict
    ) -> None:
        try:
            from bot.services.agent_lead_service import AgentLeadService

            lead_label = str((result.get("metadata") or {}).get("lead_label") or "general")
            lead_service = AgentLeadService(session)
            await lead_service.capture_lead(
                agent_id=agent.id,
                group_id=agent.group_id or 0,
                tg_user_id=event.user_id,
                username=str(event.payload.get("username") or ""),
                first_name=str(event.payload.get("first_name") or ""),
                last_name=str(event.payload.get("full_name") or "").split()[-1] if event.payload.get("full_name") else None,
                source_group_tg_id=event.payload.get("chat_id") or event.group_id,
                source_group_title=str(event.payload.get("group_title") or ""),
                source_message_id=event.payload.get("message_id"),
                message_text=str(event.payload.get("text") or ""),
                lead_label=lead_label,
                confidence=0.6,
            )
        except Exception:
            logger.exception("lead_capture_persistence_failed", agent_id=agent.id)
            try:
                await session.rollback()
            except Exception:
                pass
