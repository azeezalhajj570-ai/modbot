from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import DailyGroupSummary, Group, GroupSummarySettings
from bot.summaries.collector import collect_group_activity
from bot.summaries.delivery import send_daily_summary
from bot.summaries.generator import DeterministicSummaryGenerator, build_summary_generator, generate_with_fallback


def _settings_timezone(settings: GroupSummarySettings) -> ZoneInfo:
    try:
        return ZoneInfo(settings.timezone or "Asia/Aden")
    except ZoneInfoNotFoundError:
        return ZoneInfo("Asia/Aden")


def _summary_window(settings: GroupSummarySettings, summary_date: date) -> tuple[datetime, datetime]:
    tz = _settings_timezone(settings)
    start_local = datetime.combine(summary_date, time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc).replace(tzinfo=None), end_local.astimezone(timezone.utc).replace(tzinfo=None)


class DailyAdminSummaryService:
    def __init__(self, session: AsyncSession, *, bot=None, generator=None) -> None:
        self.session = session
        self.bot = bot
        self.generator = generator or build_summary_generator()
        self.fallback_generator = DeterministicSummaryGenerator()

    async def get_settings(self, group_id: int) -> GroupSummarySettings:
        existing = (
            await self.session.execute(select(GroupSummarySettings).where(GroupSummarySettings.group_id == group_id))
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        settings = GroupSummarySettings(group_id=group_id)
        self.session.add(settings)
        try:
            await self.session.flush()
        except IntegrityError:
            await self.session.rollback()
            return (
                await self.session.execute(select(GroupSummarySettings).where(GroupSummarySettings.group_id == group_id))
            ).scalar_one()
        return settings

    async def update_settings(self, group_id: int, payload: dict[str, object]) -> GroupSummarySettings:
        settings = await self.get_settings(group_id)
        for field, value in payload.items():
            if hasattr(settings, field) and value is not None:
                setattr(settings, field, value)
        await self.session.commit()
        await self.session.refresh(settings)
        return settings

    async def list_summaries(self, group_id: int, *, limit: int = 30) -> list[DailyGroupSummary]:
        return (
            await self.session.execute(
                select(DailyGroupSummary)
                .where(DailyGroupSummary.group_id == group_id)
                .order_by(DailyGroupSummary.summary_date.desc(), DailyGroupSummary.id.desc())
                .limit(limit)
            )
        ).scalars().all()

    async def generate_summary_for_group(
        self,
        group_id: int,
        summary_date: date,
        *,
        deliver: bool = True,
    ) -> DailyGroupSummary:
        existing = (
            await self.session.execute(
                select(DailyGroupSummary).where(
                    DailyGroupSummary.group_id == group_id,
                    DailyGroupSummary.summary_date == summary_date,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        group = (await self.session.execute(select(Group).where(Group.id == group_id))).scalar_one()
        settings = await self.get_settings(group_id)
        start_at, end_at = _summary_window(settings, summary_date)
        activity = await collect_group_activity(
            self.session,
            group_id=group_id,
            start_at=start_at,
            end_at=end_at,
            max_message_samples=settings.max_message_samples,
        )

        if isinstance(self.generator, DeterministicSummaryGenerator):
            result = await self.generator.generate_daily_summary(group, settings, activity, moderation_events=activity.moderation_highlights)
        else:
            result = await generate_with_fallback(
                primary=self.generator,
                fallback=self.fallback_generator,
                group=group,
                settings=settings,
                activity=activity,
            )

        summary = DailyGroupSummary(
            group_id=group_id,
            summary_date=summary_date,
            total_messages=activity.total_messages,
            active_users_count=activity.active_users_count,
            links_count=activity.links_count,
            suspicious_messages_count=activity.suspicious_messages_count,
            deleted_messages_count=activity.deleted_messages_count,
            top_users=activity.top_users if settings.include_top_users else [],
            top_topics=result.top_topics,
            important_questions=result.important_questions,
            unanswered_questions=result.unanswered_questions,
            links=activity.links if settings.include_links else [],
            moderation_highlights=result.moderation_highlights,
            recommendations=result.recommendations,
            summary_text=result.summary_text,
            status="generated",
        )
        self.session.add(summary)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            return (
                await self.session.execute(
                    select(DailyGroupSummary).where(
                        DailyGroupSummary.group_id == group_id,
                        DailyGroupSummary.summary_date == summary_date,
                    )
                )
            ).scalar_one()

        if deliver:
            try:
                summary.status = await send_daily_summary(self.session, group=group, summary=summary, settings=settings, bot=self.bot)
                summary.error_message = None
            except Exception as exc:
                summary.status = "failed"
                summary.error_message = str(exc)
            await self.session.commit()
        return summary

    async def run_due_summaries(self, *, now_utc: datetime | None = None) -> list[DailyGroupSummary]:
        now = now_utc or datetime.utcnow()
        rows = (
            await self.session.execute(
                select(GroupSummarySettings)
                .join(Group, Group.id == GroupSummarySettings.group_id)
                .where(GroupSummarySettings.enabled.is_(True), Group.is_active.is_(True))
            )
        ).scalars().all()
        generated: list[DailyGroupSummary] = []
        for settings in rows:
            tz = _settings_timezone(settings)
            local_now = now.replace(tzinfo=timezone.utc).astimezone(tz)
            if local_now.strftime("%H:%M") != (settings.summary_time or "21:00"):
                continue
            target_date = (local_now - timedelta(days=1)).date()
            generated.append(await self.generate_summary_for_group(settings.group_id, target_date, deliver=True))
        return generated
