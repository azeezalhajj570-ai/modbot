from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from aiogram import Bot
from fastapi import HTTPException, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import get_settings
from bot.core.runtime.audit import AuditEntry, ModerationLogAuditSink, RuntimeAuditService
from bot.db.models import Group, GroupSetting, ModerationEvent, ModerationLog, PluginEnabled, ScrapedGroup, ScrapedMember, ScrapedMessage, Warning
from bot.db.models.agent import AgentLead
from bot.services.group_service import tg_group_id_candidates

class AdminActivityService:
    def __init__(self, session: AsyncSession, *, bot_factory: type[Bot] | None = None) -> None:
        self.session = session
        self.bot_factory = bot_factory or Bot

    async def build_group_overview(self, *, group_id: int) -> dict[str, Any]:
        group = (await self.session.execute(select(Group).where(Group.id == group_id))).scalar_one_or_none()
        if not group:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

        settings_count = (
            await self.session.execute(select(func.count(GroupSetting.id)).where(GroupSetting.group_id == group_id))
        ).scalar_one()
        enabled_plugins = (
            await self.session.execute(
                select(func.count(PluginEnabled.id)).where(PluginEnabled.group_id == group_id, PluginEnabled.enabled.is_(True))
            )
        ).scalar_one()
        warning_total = (
            await self.session.execute(select(func.coalesce(func.sum(Warning.count), 0)).where(Warning.group_id == group_id))
        ).scalar_one()
        total_leads = (
            await self.session.execute(
                select(func.count(func.distinct(ModerationLog.target_user_id))).where(ModerationLog.group_id == group_id, ModerationLog.action == "lead_captured")
            )
        ).scalar_one()

        agent_leads_count = (
            await self.session.execute(
                select(func.count(AgentLead.id)).where(AgentLead.group_id == group_id)
            )
        ).scalar_one()

        total_leads = int(total_leads) + int(agent_leads_count)
        recent_rows = (
            await self.session.execute(
                select(ModerationLog.action, ModerationLog.reason, ModerationLog.admin_user_id, ModerationLog.created_at, ModerationLog.details)
                .where(ModerationLog.group_id == group_id)
                .order_by(desc(ModerationLog.created_at))
                .limit(20)
            )
        ).all()
        active_moderators = (
            await self.session.execute(
                select(func.count(func.distinct(ModerationLog.admin_user_id))).where(
                    ModerationLog.group_id == group_id,
                    ModerationLog.admin_user_id.is_not(None),
                )
            )
        ).scalar_one()
        scraped_group = (
            await self.session.execute(select(ScrapedGroup).where(ScrapedGroup.tg_group_id.in_(tg_group_id_candidates(int(group.tg_group_id)))))
        ).scalar_one_or_none()
        scraped_members_count = 0
        scraped_messages_count = 0
        if scraped_group is not None:
            scraped_members_count = int(
                (
                    await self.session.execute(
                        select(func.count(ScrapedMember.id)).where(ScrapedMember.scraped_group_id == scraped_group.id)
                    )
                ).scalar_one()
                or 0
            )
            scraped_messages_count = int(
                (
                    await self.session.execute(
                        select(func.count(ScrapedMessage.id)).where(ScrapedMessage.scraped_group_id == scraped_group.id)
                    )
                ).scalar_one()
                or 0
            )

        # Moderation event counts
        spam_detected = int(
            (
                await self.session.execute(
                    select(func.count(ModerationEvent.id)).where(
                        ModerationEvent.group_id == group_id,
                        ModerationEvent.action_taken.in_(["delete", "warn", "ban", "mute"]),
                    )
                )
            ).scalar_one()
            or 0
        )

        messages_deleted = int(
            (
                await self.session.execute(
                    select(func.count(ModerationLog.id)).where(
                        ModerationLog.group_id == group_id,
                        ModerationLog.action == "delete_message",
                    )
                )
            ).scalar_one()
            or 0
        )

        recent_events_rows = (
            await self.session.execute(
                select(
                    ModerationEvent.id,
                    ModerationEvent.category,
                    ModerationEvent.text_preview,
                    ModerationEvent.username,
                    ModerationEvent.confidence,
                    ModerationEvent.action_taken,
                    ModerationEvent.created_at,
                )
                .where(ModerationEvent.group_id == group_id)
                .order_by(desc(ModerationEvent.created_at))
                .limit(10)
            )
        ).all()

        return {
            "group": {"id": group.id, "title": group.title, "tg_group_id": group.tg_group_id},
            "stats": {
                "configured_settings": int(settings_count),
                "enabled_plugins": int(enabled_plugins),
                "total_warnings": int(warning_total),
                "total_leads": int(total_leads),
                "active_moderators": int(active_moderators),
                "members_count": scraped_members_count,
                "messages_count": scraped_messages_count,
                "spam_detected": spam_detected,
                "messages_deleted": messages_deleted,
                "member_growth": {"tracked_admin_accounts": scraped_members_count},
                "message_activity": self._tally_recent_activity(recent_rows),
            },
            "recent_actions": [
                {
                    "action": row.action,
                    "reason": row.reason,
                    "moderator_id": row.admin_user_id,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "details": row.details,
                }
                for row in recent_rows
            ],
            "recent_events": [
                {
                    "id": row.id,
                    "category": row.category,
                    "text_preview": row.text_preview,
                    "username": row.username,
                    "confidence": row.confidence,
                    "action_taken": row.action_taken,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in recent_events_rows
            ],
        }

    async def list_leads(self, *, group_id: int) -> list[dict[str, Any]]:
        rows = (
            await self.session.execute(
                select(ModerationLog.target_user_id, ModerationLog.reason, ModerationLog.details, ModerationLog.created_at)
                .where(ModerationLog.group_id == group_id, ModerationLog.action == "lead_captured")
                .order_by(desc(ModerationLog.created_at), desc(ModerationLog.id))
                .limit(50)
            )
        ).all()
        return [
            {
                "user_id": row.target_user_id,
                "label": (row.details or {}).get("lead_label"),
                "message_text": (row.details or {}).get("message_text"),
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "reason": row.reason,
            }
            for row in rows
        ]

    async def list_notification_reports(self, *, group_id: int, limit: int) -> list[dict[str, Any]]:
        rows = (
            await self.session.execute(
                select(ModerationLog.id, ModerationLog.target_user_id, ModerationLog.reason, ModerationLog.details, ModerationLog.created_at)
                .where(ModerationLog.group_id == group_id, ModerationLog.action == "destination_notified")
                .order_by(desc(ModerationLog.created_at), desc(ModerationLog.id))
                .limit(limit)
            )
        ).all()
        return [
            {
                "id": row.id,
                "group_id": group_id,
                "user_id": row.target_user_id,
                "reason": row.reason,
                "message_text": (row.details or {}).get("message_text"),
                "rendered_text": (row.details or {}).get("text"),
                "destination": (row.details or {}).get("destination"),
                "delivery_mode": (row.details or {}).get("delivery_mode"),
                "source_chat_id": (row.details or {}).get("source_chat_id"),
                "source_group_title": (row.details or {}).get("source_group_title"),
                "source_message_id": (row.details or {}).get("source_message_id"),
                "source_user_id": (row.details or {}).get("source_user_id"),
                "task_key": (row.details or {}).get("task_key"),
                "assignment_id": (row.details or {}).get("assignment_id"),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]

    async def reply_to_notification_report(
        self,
        *,
        group_id: int,
        log_id: int,
        actor_user_id: int,
        text: str,
    ) -> dict[str, Any]:
        log_row = (
            await self.session.execute(
                select(ModerationLog).where(
                    ModerationLog.group_id == group_id,
                    ModerationLog.id == log_id,
                    ModerationLog.action == "destination_notified",
                )
            )
        ).scalar_one_or_none()
        if log_row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification report not found")

        details = dict(log_row.details or {})
        destination_chat_id = self._resolve_destination_chat_id(details)
        reply_to_message_id = self._resolve_reply_to_message_id(details)
        text_value = text.strip()

        bot = self.bot_factory(token=get_settings().bot_token)
        try:
            sent = await bot.send_message(
                chat_id=destination_chat_id,
                text=text_value,
                reply_to_message_id=reply_to_message_id,
            )
        finally:
            await bot.session.close()

        await RuntimeAuditService(ModerationLogAuditSink(self.session)).record(
            AuditEntry(
                action="notification_report_reply",
                group_id=group_id,
                actor_user_id=actor_user_id,
                target_user_id=log_row.target_user_id,
                domain="admin",
                event_type="admin.notification_report_reply_requested",
                action_type="notification_report_reply",
                source_runtime="admin.service",
                reason=text_value,
                details={
                    "selected_actions": ["notification_report_reply"],
                    "guard_outcomes": [],
                    "execution_result": {
                        "destination_chat_id": str(destination_chat_id),
                        "reply_to_message_id": reply_to_message_id,
                        "sent_message_id": str(getattr(sent, "message_id", "") or ""),
                    },
                    "source_log_id": log_row.id,
                    "destination_chat_id": str(destination_chat_id),
                    "destination_message_id": str(reply_to_message_id or ""),
                    "source_chat_id": str(details.get("source_chat_id") or ""),
                    "source_message_id": str(details.get("source_message_id") or ""),
                    "source_user_id": str(details.get("source_user_id") or ""),
                    "source_group_title": str(details.get("source_group_title") or ""),
                    "sent_message_id": str(getattr(sent, "message_id", "") or ""),
                    "source": "webapp",
                },
            )
        )
        await self.session.commit()
        return {
            "status": "ok",
            "log_id": log_row.id,
            "sent_message_id": getattr(sent, "message_id", None),
            "destination_chat_id": destination_chat_id,
            "reply_to_message_id": reply_to_message_id,
        }

    async def list_logs(self, *, group_id: int, limit: int) -> list[dict[str, Any]]:
        rows = (
            await self.session.execute(
                select(
                    ModerationLog.action,
                    ModerationLog.target_user_id,
                    ModerationLog.admin_user_id,
                    ModerationLog.reason,
                    ModerationLog.details,
                    ModerationLog.created_at,
                )
                .where(ModerationLog.group_id == group_id)
                .order_by(desc(ModerationLog.created_at))
                .limit(limit)
            )
        ).all()
        return [
            {
                "action": row.action,
                "target_user_id": row.target_user_id,
                "moderator_id": row.admin_user_id,
                "reason": row.reason,
                "details": row.details if isinstance(row.details, dict) else json.loads("{}"),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]

    @staticmethod
    def _resolve_destination_chat_id(details: dict[str, Any]) -> int | str:
        destination_chat_id: int | str | None = details.get("destination_chat_id")
        if destination_chat_id in (None, ""):
            destination_chat_id = details.get("destination")
        if destination_chat_id in (None, ""):
            source_chat_id_raw = details.get("source_chat_id")
            if source_chat_id_raw in (None, ""):
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Notification destination chat is missing")
            try:
                destination_chat_id = int(source_chat_id_raw)
            except (TypeError, ValueError):
                destination_chat_id = source_chat_id_raw

        if isinstance(destination_chat_id, str):
            destination_chat_id = destination_chat_id.strip()
            if not destination_chat_id:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Notification destination chat is invalid")
            if destination_chat_id.lstrip("-").isdigit():
                destination_chat_id = int(destination_chat_id)
        return destination_chat_id

    @staticmethod
    def _resolve_reply_to_message_id(details: dict[str, Any]) -> int | None:
        destination_message_id_raw = details.get("destination_message_id")
        if destination_message_id_raw in (None, ""):
            destination_message_id_raw = details.get("sent_message_id")
        if destination_message_id_raw in (None, "") and details.get("destination_chat_id") in (None, ""):
            destination_message_id_raw = details.get("source_message_id")
        if destination_message_id_raw in (None, ""):
            return None
        try:
            return int(destination_message_id_raw)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _tally_recent_activity(rows: list[Any]) -> dict[str, int]:
        message_activity: dict[str, int] = defaultdict(int)
        for row in rows:
            date_key = row.created_at.date().isoformat() if row.created_at else "unknown"
            message_activity[date_key] += 1
        return dict(sorted(message_activity.items()))
