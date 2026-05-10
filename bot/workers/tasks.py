from __future__ import annotations

import asyncio
from datetime import datetime
from datetime import date as date_cls

import dramatiq
from aiogram import Bot
from sqlalchemy import select

from bot.agents.runtime import UserAgentExecutor
from bot.agents.session import SessionManager
from bot.ai.moderation import ModerationDecision, build_default_pipeline
from bot.agents.dispatch import dispatch_agent_job
from bot.config import get_settings
from bot.core.runtime.automation import AutomationRuntimeService, TaskFollowUpRequest
from bot.core.runtime.admin import AdminAutomationRuntimeService
from bot.core.runtime.moderation import FlaggedMessageModerationRequest, FlaggedWarningModerationRequest, ModerationRuntimeService
from bot.db.models import Agent, Group, GroupAdminRole, ModerationLog, SubscriptionRequest, SubscriptionStatus
from bot.db.session import SessionLocal
from bot.services.group_service import tg_group_id_candidates
from bot.services.moderation_settings_store import ModerationSettingsStore
from bot.services.scheduled_message_service import ScheduledMessageService
from bot.services.task_activity_service import TaskActivityService
from bot.summaries.scheduler import generate_summary_for_group as generate_group_summary_job
from bot.summaries.scheduler import run_daily_summary_scheduler
from bot.tasks.membership_tasks import (
    add_user_to_group,
    add_user_to_group_task,
    _run_add_user_to_group_task_with_agent,
)
from bot.workers.app import redis_broker  # noqa: F401

pipeline = build_default_pipeline()

run_membership_add_job = add_user_to_group_task

@dramatiq.actor(queue_name="subscriptions")
def check_expiring_subscriptions() -> None:
    asyncio.run(_check_expiring_subscriptions())


async def _check_expiring_subscriptions() -> None:
    from bot.services.group_expiry_service import GroupExpiryService
    async with SessionLocal() as session:
        service = GroupExpiryService(session)
        await service.check_expiring_subscriptions()


@dramatiq.actor(queue_name="moderation")
def run_spam_analysis(chat_id: int, message_id: int, user_id: int, text: str, lang: str) -> None:
    asyncio.run(_run_spam_analysis(chat_id, message_id, user_id, text, lang))


async def _run_spam_analysis(chat_id: int, message_id: int, user_id: int, text: str, lang: str) -> None:
    result = await pipeline.process(text)
    if result.decision == ModerationDecision.ALLOW:
        return

    async with SessionLocal() as session:
        group = (
            await session.execute(select(Group).where(Group.tg_group_id.in_(tg_group_id_candidates(chat_id))))
        ).scalar_one_or_none()
        if not group:
            return

        moderation_settings = await ModerationSettingsStore(session).get_settings(group.id)
        if not moderation_settings.anti_spam:
            return

        admin_role = (
            await session.execute(
                select(GroupAdminRole.id).where(
                    GroupAdminRole.group_id == group.id,
                    GroupAdminRole.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if admin_role is not None:
            return

        bot = Bot(token=get_settings().bot_token)
        try:
            if result.decision == ModerationDecision.DELETE:
                await ModerationRuntimeService(session).enforce_flagged_message(
                    FlaggedMessageModerationRequest(
                        group_id=group.id,
                        chat_id=chat_id,
                        message_id=message_id,
                        target_user_id=user_id,
                        source="anti_spam",
                        reason=result.reason,
                        score=result.score,
                        notice_key="anti_spam_delete",
                        feature_key="anti_spam",
                        delete_log_action="delete_spam",
                        mute_setting_key="anti_spam_mute",
                        mute_threshold_key="anti_spam_mute_limit",
                        mute_log_action="mute_spam_user",
                        incident_actions=("warn_spam", "delete_spam"),
                        target_is_admin=admin_role is not None,
                        lang=lang,
                        metadata={"message_id": message_id},
                    ),
                    bot=bot,
                )
            elif result.decision == ModerationDecision.WARN:
                await ModerationRuntimeService(session).enforce_flagged_warning(
                    FlaggedWarningModerationRequest(
                        group_id=group.id,
                        chat_id=chat_id,
                        target_user_id=user_id,
                        source="anti_spam",
                        reason=result.reason,
                        score=result.score,
                        notice_key="anti_spam_warn",
                        log_action="warn_spam",
                        mute_setting_key="anti_spam_mute",
                        mute_threshold_key="anti_spam_mute_limit",
                        mute_log_action="mute_spam_user",
                        lang=lang,
                        metadata={"message_id": message_id},
                    ),
                    bot=bot,
                )
            await session.commit()
        finally:
            await bot.session.close()


@dramatiq.actor(queue_name="analytics")
def aggregate_group_analytics(group_id: int) -> None:
    asyncio.run(_aggregate_group_analytics(group_id))


async def _aggregate_group_analytics(group_id: int) -> None:
    from bot.services.admin_activity_service import AdminActivityService
    async with SessionLocal() as session:
        service = AdminActivityService(session)
        try:
            overview = await service.build_group_overview(group_id)
            logger.info("group_analytics_aggregated", group_id=group_id, overview_keys=list(overview.keys()) if overview else None)
        except Exception as exc:
            logger.warning("group_analytics_failed", group_id=group_id, error=str(exc))


@dramatiq.actor(queue_name="cleanup")
def cleanup_expired_messages(group_id: int) -> None:
    asyncio.run(_cleanup_expired_messages(group_id))


async def _cleanup_expired_messages(group_id: int) -> None:
    from datetime import timedelta
    from bot.db.models import ModerationLog
    cutoff = datetime.utcnow() - timedelta(days=90)
    async with SessionLocal() as session:
        result = await session.execute(
            select(ModerationLog).where(
                ModerationLog.group_id == group_id,
                ModerationLog.created_at < cutoff,
            )
        )
        expired = result.scalars().all()
        for log in expired:
            await session.delete(log)
        await session.commit()
        if expired:
            logger.info("expired_messages_cleaned", group_id=group_id, count=len(expired))


def _dispatch_follow_up(
    *,
    delay_seconds: int,
    group_id: int,
    chat_id: int,
    executor_type: str,
    agent_id: int | None,
    text: str,
    assignment_id: str,
    task_key: str,
    target_user_id: int | None,
    delete_after_seconds: int = 0,
) -> None:
    run_task_follow_up.send_with_options(
        args=(
            group_id,
            chat_id,
            executor_type,
            agent_id,
            text,
            assignment_id,
            task_key,
            target_user_id,
            delete_after_seconds,
        ),
        delay=delay_seconds * 1000,
    )


def schedule_task_follow_up(
    *,
    delay_seconds: int,
    group_id: int,
    chat_id: int,
    executor_type: str,
    agent_id: int | None,
    text: str,
    assignment_id: str,
    task_key: str,
    target_user_id: int | None,
    delete_after_seconds: int = 0,
) -> None:
    _dispatch_follow_up(
        delay_seconds=delay_seconds,
        group_id=group_id,
        chat_id=chat_id,
        executor_type=executor_type,
        agent_id=agent_id,
        text=text,
        assignment_id=assignment_id,
        task_key=task_key,
        target_user_id=target_user_id,
        delete_after_seconds=delete_after_seconds,
    )


def schedule_scheduled_announcement(*, delay_seconds: int, group_id: int, entry_id: str, expected_send_at: str | None = None) -> None:
    run_scheduled_announcement.send_with_options(args=(group_id, entry_id, expected_send_at or ""), delay=max(delay_seconds, 0) * 1000)


def schedule_bot_message_delete(*, delay_seconds: int, chat_id: int, message_id: int) -> None:
    run_bot_message_delete.send_with_options(args=(chat_id, message_id), delay=max(delay_seconds, 0) * 1000)


@dramatiq.actor(queue_name="automation")
def run_task_follow_up(
    group_id: int,
    chat_id: int,
    executor_type: str,
    agent_id: int | None,
    text: str,
    assignment_id: str,
    task_key: str,
    target_user_id: int | None,
    delete_after_seconds: int = 0,
) -> None:
    asyncio.run(
        _run_task_follow_up(
            group_id,
            chat_id,
            executor_type,
            agent_id,
            text,
            assignment_id,
            task_key,
            target_user_id,
            delete_after_seconds,
        )
    )


@dramatiq.actor(queue_name="automation")
def run_scheduled_announcement(group_id: int, entry_id: str, expected_send_at: str = "") -> None:
    asyncio.run(_run_scheduled_announcement(group_id, entry_id, expected_send_at))


@dramatiq.actor(queue_name="cleanup")
def run_bot_message_delete(chat_id: int, message_id: int) -> None:
    asyncio.run(_run_bot_message_delete(chat_id, message_id))


@dramatiq.actor(queue_name="notifications")
def notify_expiring_subscriptions() -> None:
    asyncio.run(_notify_expiring_subscriptions())


@dramatiq.actor(queue_name="cleanup")
def deactivate_expired_subscriptions() -> None:
    asyncio.run(_deactivate_expired_subscriptions())


@dramatiq.actor(queue_name="analytics")
def run_daily_admin_summaries() -> None:
    asyncio.run(_run_daily_admin_summaries())


@dramatiq.actor(queue_name="analytics")
def generate_daily_admin_summary(group_id: int, summary_date: str) -> None:
    asyncio.run(_generate_daily_admin_summary(group_id, summary_date))


async def _notify_expiring_subscriptions() -> None:
    from datetime import timedelta
    now = datetime.utcnow()
    warning_window = now + timedelta(hours=24)
    
    async with SessionLocal() as session:
        # Find approved subscriptions expiring in the next 24 hours that haven't been notified yet
        # (Assuming we track notification status, but for now just send if expires_at is near)
        stmt = select(SubscriptionRequest).where(
            SubscriptionRequest.status == SubscriptionStatus.APPROVED.value,
            SubscriptionRequest.expires_at > now,
            SubscriptionRequest.expires_at <= warning_window,
        )
        expiring = (await session.execute(stmt)).scalars().all()
        
        if not expiring:
            return
            
        bot = Bot(token=get_settings().bot_token)
        try:
            for sub in expiring:
                try:
                    await bot.send_message(
                        sub.tg_user_id,
                        f"Your agent subscription will expire on {sub.expires_at.strftime('%Y-%m-%d %H:%M')}. "
                        "Redeem a new promo code to maintain access."
                    )
                except Exception:
                    pass
        finally:
            await bot.session.close()


async def _deactivate_expired_subscriptions() -> None:
    from bot.db.models import SubscriptionRequest, SubscriptionStatus, Agent
    now = datetime.utcnow()
    async with SessionLocal() as session:
        stmt = select(SubscriptionRequest).where(
            SubscriptionRequest.status == SubscriptionStatus.APPROVED.value,
            SubscriptionRequest.expires_at.is_not(None),
            SubscriptionRequest.expires_at < now,
        )
        expired = (await session.execute(stmt)).scalars().all()
        for sub in expired:
            sub.status = SubscriptionStatus.CANCELLED.value
            logger.info("subscription_expired", sub_id=sub.id, tg_user_id=sub.tg_user_id)
        await session.commit()

        # Deactivate agents whose owner has no active subscription
        expiry_window = now - timedelta(hours=24)
        agent_stmt = select(Agent).where(
            Agent.status == "active",
            Agent.created_at < expiry_window,
        )
        agents = (await session.execute(agent_stmt)).scalars().all()
        for agent in agents:
            agent.status = "inactive"
        await session.commit()
        if agents:
            logger.info("agents_deactivated_after_expiry", count=len(agents))


async def _run_daily_admin_summaries() -> None:
    bot = Bot(token=get_settings().bot_token)
    try:
        await run_daily_summary_scheduler(bot=bot)
    finally:
        await bot.session.close()


async def _generate_daily_admin_summary(group_id: int, summary_date: str) -> None:
    bot = Bot(token=get_settings().bot_token)
    try:
        await generate_group_summary_job(group_id, date_cls.fromisoformat(summary_date), bot=bot)
    finally:
        await bot.session.close()


async def _run_task_follow_up(
    group_id: int,
    chat_id: int,
    executor_type: str,
    agent_id: int | None,
    text: str,
    assignment_id: str,
    task_key: str,
    target_user_id: int | None,
    delete_after_seconds: int = 0,
) -> None:
    if not text.strip():
        return

    async with SessionLocal() as session:
        if executor_type == "agent" and agent_id is not None:
            agent = (await session.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
            if agent is None:
                return
            client = await SessionManager(session_factory=SessionLocal).get_client(agent_id)
            try:
                await UserAgentExecutor().execute(client=client, payload={"group_id": group_id, "chat_id": chat_id, "text": text})
            finally:
                await client.disconnect()
        else:
            bot = Bot(token=get_settings().bot_token)
            try:
                await AutomationRuntimeService(
                    session,
                    dispatch_delete_message=schedule_bot_message_delete,
                ).execute_task_follow_up(
                    TaskFollowUpRequest(
                        group_id=group_id,
                        assignment_id=assignment_id,
                        task_key=task_key,
                        chat_id=chat_id,
                        text=text,
                        target_user_id=target_user_id,
                        delete_after_seconds=delete_after_seconds,
                        metadata={"executor_type": executor_type},
                    ),
                    bot=bot,
                )
            finally:
                await bot.session.close()

        if executor_type == "agent":
            await TaskActivityService(session).log_follow_up_sent(
                group_id=group_id,
                target_user_id=target_user_id,
                task_key=task_key,
                assignment_id=assignment_id,
                executor_type=executor_type,
            )


async def _run_bot_message_delete(chat_id: int, message_id: int) -> None:
    bot = Bot(token=get_settings().bot_token)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    finally:
        await bot.session.close()


async def _run_scheduled_announcement(group_id: int, entry_id: str, expected_send_at: str = "") -> None:
    async with SessionLocal() as session:
        service = ScheduledMessageService(session)
        entry = await service.get_entry(group_id=group_id, entry_id=entry_id)
        if entry is None or entry.get("status") == "sent":
            return
        admin_runtime = AdminAutomationRuntimeService(
            session,
            dispatch_agent_job=dispatch_agent_job,
            dispatch_delete_message=schedule_bot_message_delete,
        )

        send_at = entry.get("send_at")
        if not isinstance(send_at, str):
            return

        if expected_send_at and expected_send_at != send_at:
            send_at_dt = datetime.fromisoformat(send_at)
            now = datetime.utcnow()
            if send_at_dt > now:
                schedule_scheduled_announcement(
                    delay_seconds=max(1, int((send_at_dt - now).total_seconds())),
                    group_id=group_id,
                    entry_id=entry_id,
                    expected_send_at=send_at,
                )
            return

        send_at_dt = datetime.fromisoformat(send_at)
        now = datetime.utcnow()
        if send_at_dt > now:
            schedule_scheduled_announcement(
                delay_seconds=max(1, int((send_at_dt - now).total_seconds())),
                group_id=group_id,
                entry_id=entry_id,
                expected_send_at=send_at,
            )
            return

        bot = Bot(token=get_settings().bot_token)
        try:
            request = await admin_runtime.get_scheduled_message_dispatch_request(group_id=group_id, entry_id=entry_id)
            if request is None:
                return
            await AutomationRuntimeService(
                session,
                dispatch_delete_message=schedule_bot_message_delete,
            ).execute_scheduled_announcement(request, bot=bot)
        finally:
            await bot.session.close()

        updated = await admin_runtime.mark_scheduled_message_delivered(
            group_id=group_id,
            entry_id=entry_id,
            delivered_at=now,
        )
        if updated and updated.get("cron"):
            next_send_at = updated.get("send_at")
            if isinstance(next_send_at, str):
                next_send_at_dt = datetime.fromisoformat(next_send_at)
                schedule_scheduled_announcement(
                    delay_seconds=max(1, int((next_send_at_dt - now).total_seconds())),
                    group_id=group_id,
                    entry_id=entry_id,
                )
