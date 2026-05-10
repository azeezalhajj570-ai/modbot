from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Group
from bot.services.scheduled_message_store import ScheduledMessageEntry, ScheduledMessageStore

_CRON_FIELD_RANGES = (
    (0, 59),
    (0, 23),
    (1, 31),
    (1, 12),
    (0, 6),
)
class ScheduledMessageService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.store = ScheduledMessageStore(session)

    async def list_entries(self, *, group_id: int) -> list[dict[str, Any]]:
        return [entry.to_dict() for entry in await self.store.list_entries(group_id)]

    async def get_entry(self, *, group_id: int, entry_id: str) -> dict[str, Any] | None:
        entry = await self.store.get_entry(group_id, entry_id)
        return entry.to_dict() if entry is not None else None

    async def save_entry(
        self,
        *,
        group_id: int,
        text: str,
        schedule: str,
        entry_id: str | None = None,
        delete_after_seconds: int | None = None,
    ) -> dict[str, Any]:
        await self._ensure_group_exists(group_id)
        normalized_text = text.strip()
        if not normalized_text:
            raise ValueError("text is required")

        parsed = self.parse_schedule_time(schedule)
        if parsed is None:
            raise ValueError(
                "Invalid schedule time. Use `now`, `+10m`, `+2h`, `YYYY-MM-DD HH:MM`, or a 5-field cron expression."
            )

        send_at, cron_expression = parsed
        normalized = ScheduledMessageEntry(
            id=entry_id or uuid4().hex,
            text=normalized_text,
            send_at=send_at.isoformat(timespec="minutes"),
            status="pending",
            cron=cron_expression,
            delete_after_seconds=max(0, int(delete_after_seconds or 0)) or None,
        )

        await self.store.save_entry(group_id, normalized)
        return normalized.to_dict()

    async def delete_entry(self, *, group_id: int, entry_id: str) -> bool:
        return await self.store.delete_entry(group_id, entry_id)

    async def mark_delivered(self, *, group_id: int, entry_id: str, delivered_at: datetime | None = None) -> dict[str, Any] | None:
        delivered = delivered_at or datetime.utcnow()
        entries = await self.store.list_entries(group_id)
        updated: list[ScheduledMessageEntry] = []
        result: ScheduledMessageEntry | None = None

        for entry in entries:
            if entry.id != entry_id:
                updated.append(entry)
                continue

            if entry.cron:
                next_send_at = self.next_cron_datetime(entry.cron, now=delivered)
                if next_send_at is None:
                    result = ScheduledMessageEntry(
                        id=entry.id,
                        text=entry.text,
                        send_at=entry.send_at,
                        status="failed",
                        cron=entry.cron,
                        sent_at=delivered.isoformat(),
                        delete_after_seconds=entry.delete_after_seconds,
                    )
                else:
                    result = ScheduledMessageEntry(
                        id=entry.id,
                        text=entry.text,
                        send_at=next_send_at.isoformat(timespec="minutes"),
                        status="pending",
                        cron=entry.cron,
                        sent_at=delivered.isoformat(),
                        delete_after_seconds=entry.delete_after_seconds,
                    )
            else:
                result = ScheduledMessageEntry(
                    id=entry.id,
                    text=entry.text,
                    send_at=entry.send_at,
                    status="sent",
                    cron=entry.cron,
                    sent_at=delivered.isoformat(),
                    delete_after_seconds=entry.delete_after_seconds,
                )
            updated.append(result)

        if result is None:
            return None
        await self.store.replace_entries(group_id, updated)
        return result.to_dict()

    async def due_entries(self, *, group_id: int, now: datetime | None = None) -> list[dict[str, Any]]:
        current = now or datetime.utcnow()
        due: list[dict[str, Any]] = []
        for entry in await self.store.list_entries(group_id):
            if entry.status == "sent":
                continue
            if datetime.fromisoformat(entry.send_at) <= current:
                due.append(entry.to_dict())
        return due

    @staticmethod
    def parse_schedule_time(raw: str) -> tuple[datetime, str | None] | None:
        value = raw.strip().lower()
        now = datetime.utcnow()
        if value == "now":
            return now, None
        if value.startswith("+") and value.endswith("m"):
            minutes = value[1:-1]
            if minutes.isdigit():
                return now.replace(second=0, microsecond=0) + timedelta(minutes=int(minutes)), None
        if value.startswith("+") and value.endswith("h"):
            hours = value[1:-1]
            if hours.isdigit():
                return now.replace(second=0, microsecond=0) + timedelta(hours=int(hours)), None
        try:
            return datetime.strptime(raw.strip(), "%Y-%m-%d %H:%M"), None
        except ValueError:
            cron_send_at = ScheduledMessageService.next_cron_datetime(raw.strip(), now=now)
            if cron_send_at is None:
                return None
            return cron_send_at, raw.strip()

    @staticmethod
    def next_cron_datetime(raw: str, *, now: datetime | None = None) -> datetime | None:
        schedule = ScheduledMessageService._parse_cron_expression(raw)
        if schedule is None:
            return None

        current = (now or datetime.utcnow()).replace(second=0, microsecond=0) + timedelta(minutes=1)
        limit = current + timedelta(days=366)
        while current <= limit:
            if ScheduledMessageService._cron_matches(current, schedule):
                return current
            current += timedelta(minutes=1)
        return None

    @staticmethod
    def _parse_cron_expression(raw: str) -> tuple[set[int], set[int], set[int], set[int], set[int]] | None:
        parts = raw.strip().split()
        if len(parts) != 5:
            return None

        fields: list[set[int]] = []
        for index, part in enumerate(parts):
            minimum, maximum = _CRON_FIELD_RANGES[index]
            parsed = ScheduledMessageService._parse_cron_field(
                part,
                minimum=minimum,
                maximum=maximum,
                sunday_alias=index == 4,
            )
            if parsed is None:
                return None
            fields.append(parsed)
        return tuple(fields)  # type: ignore[return-value]

    @staticmethod
    def _parse_cron_field(raw: str, *, minimum: int, maximum: int, sunday_alias: bool = False) -> set[int] | None:
        values: set[int] = set()
        for chunk in raw.split(","):
            item = chunk.strip()
            if not item:
                return None
            parsed = ScheduledMessageService._parse_cron_chunk(
                item,
                minimum=minimum,
                maximum=maximum,
                sunday_alias=sunday_alias,
            )
            if parsed is None:
                return None
            values.update(parsed)
        return values

    @staticmethod
    def _parse_cron_chunk(raw: str, *, minimum: int, maximum: int, sunday_alias: bool = False) -> set[int] | None:
        if raw == "*":
            return set(range(minimum, maximum + 1))

        step = 1
        base = raw
        if "/" in raw:
            parts = raw.split("/", 1)
            if len(parts) != 2 or not parts[1].isdigit():
                return None
            base, step_text = parts
            step = int(step_text)
            if step <= 0:
                return None

        if base == "*":
            start, end = minimum, maximum
        elif "-" in base:
            bounds = base.split("-", 1)
            if len(bounds) != 2:
                return None
            start = ScheduledMessageService._parse_cron_value(bounds[0], sunday_alias=sunday_alias)
            end = ScheduledMessageService._parse_cron_value(bounds[1], sunday_alias=sunday_alias)
            if start is None or end is None or start > end:
                return None
        else:
            value = ScheduledMessageService._parse_cron_value(base, sunday_alias=sunday_alias)
            if value is None:
                return None
            start, end = value, value

        if start < minimum or end > maximum:
            return None
        return set(range(start, end + 1, step))

    @staticmethod
    def _parse_cron_value(raw: str, *, sunday_alias: bool = False) -> int | None:
        if raw.isdigit():
            value = int(raw)
            if sunday_alias and value == 7:
                return 0
            return value
        return None

    @staticmethod
    def _cron_matches(dt: datetime, schedule: tuple[set[int], set[int], set[int], set[int], set[int]]) -> bool:
        minute, hour, day, month, weekday = schedule
        return (
            dt.minute in minute
            and dt.hour in hour
            and dt.day in day
            and dt.month in month
            and ((dt.weekday() + 1) % 7) in weekday
        )

    async def _ensure_group_exists(self, group_id: int) -> None:
        group = (await self.session.execute(select(Group).where(Group.id == group_id))).scalar_one_or_none()
        if group is None:
            raise ValueError("Group not found")
