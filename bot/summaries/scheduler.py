from __future__ import annotations

from datetime import date, datetime

from bot.db.session import SessionLocal
from bot.summaries.service import DailyAdminSummaryService


async def generate_summary_for_group(group_id: int, summary_date: date, *, bot=None):
    async with SessionLocal() as session:
        return await DailyAdminSummaryService(session, bot=bot).generate_summary_for_group(group_id, summary_date)


async def run_daily_summary_scheduler(*, now_utc: datetime | None = None, bot=None):
    async with SessionLocal() as session:
        return await DailyAdminSummaryService(session, bot=bot).run_due_summaries(now_utc=now_utc)
