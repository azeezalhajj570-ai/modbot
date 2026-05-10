from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bot.services.settings_service import SettingsService

SCHEDULED_MESSAGES_SETTING_KEY = "announcement_schedules"


@dataclass
class ScheduledMessageEntry:
    id: str
    text: str
    send_at: str
    status: str
    cron: str | None = None
    sent_at: str | None = None
    delete_after_seconds: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "text": self.text,
            "send_at": self.send_at,
            "status": self.status,
        }
        if self.cron:
            payload["cron"] = self.cron
        if self.sent_at:
            payload["sent_at"] = self.sent_at
        if self.delete_after_seconds is not None:
            payload["delete_after_seconds"] = self.delete_after_seconds
        return payload


class ScheduledMessageStore:
    def __init__(self, session) -> None:
        self.session = session
        self.settings = SettingsService(session)

    async def list_entries(self, group_id: int) -> list[ScheduledMessageEntry]:
        value = await self.settings.get_one(group_id, SCHEDULED_MESSAGES_SETTING_KEY)
        if not isinstance(value, list):
            return []

        entries: list[ScheduledMessageEntry] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            entry_id = str(item.get("id") or "").strip()
            text = str(item.get("text") or "").strip()
            send_at = str(item.get("send_at") or "").strip()
            status = str(item.get("status") or "").strip()
            if not entry_id or not text or not send_at or not status:
                continue
            delete_after_raw = item.get("delete_after_seconds")
            entries.append(
                ScheduledMessageEntry(
                    id=entry_id,
                    text=text,
                    send_at=send_at,
                    status=status,
                    cron=str(item.get("cron") or "").strip() or None,
                    sent_at=str(item.get("sent_at") or "").strip() or None,
                    delete_after_seconds=int(delete_after_raw) if delete_after_raw not in (None, "") else None,
                )
            )
        return entries

    async def get_entry(self, group_id: int, entry_id: str) -> ScheduledMessageEntry | None:
        for entry in await self.list_entries(group_id):
            if entry.id == entry_id:
                return entry
        return None

    async def replace_entries(self, group_id: int, entries: list[ScheduledMessageEntry]) -> None:
        await self.settings.set_value(group_id, SCHEDULED_MESSAGES_SETTING_KEY, [entry.to_dict() for entry in entries])

    async def save_entry(self, group_id: int, entry: ScheduledMessageEntry) -> ScheduledMessageEntry:
        entries = await self.list_entries(group_id)
        for index, existing in enumerate(entries):
            if existing.id == entry.id:
                entries[index] = entry
                break
        else:
            entries.append(entry)
        await self.replace_entries(group_id, entries)
        return entry

    async def delete_entry(self, group_id: int, entry_id: str) -> bool:
        entries = await self.list_entries(group_id)
        filtered = [entry for entry in entries if entry.id != entry_id]
        if len(filtered) == len(entries):
            return False
        await self.replace_entries(group_id, filtered)
        return True
