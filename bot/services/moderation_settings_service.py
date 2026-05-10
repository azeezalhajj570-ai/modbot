from __future__ import annotations

from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from bot.db.models.moderation import ModerationSetting, ModerationEvent


class ModerationSettingsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_settings(self, group_id: int) -> dict[str, Any]:
        stmt = select(ModerationSetting).where(ModerationSetting.group_id == group_id)
        settings = (await self.session.execute(stmt)).scalar_one_or_none()
        if not settings:
            settings = ModerationSetting(group_id=group_id)
            self.session.add(settings)
            await self.session.flush()
        
        return {
            "enabled": settings.enabled,
            "safe_mode": settings.safe_mode,
            "dry_run": settings.dry_run,
            "default_action": settings.default_action,
            "review_threshold": settings.review_threshold,
            "auto_delete_threshold": settings.auto_delete_threshold,
            "mute_threshold": settings.mute_threshold,
            "ban_threshold": settings.ban_threshold,
            "action_for_arabic_ads": settings.action_for_arabic_ads,
            "action_for_investment_scam": settings.action_for_investment_scam,
            "action_for_crypto_scam": settings.action_for_crypto_scam,
            "action_for_phishing_link": settings.action_for_phishing_link,
            "action_for_link_spam": settings.action_for_link_spam,
            "action_for_repeated_promo": settings.action_for_repeated_promo,
            "allowlisted_domains": settings.allowlisted_domains,
            "blocked_domains": settings.blocked_domains,
            "allowlisted_user_ids": settings.allowlisted_user_ids,
            "muted_duration_seconds": settings.muted_duration_seconds,
        }

    async def update_settings(self, group_id: int, data: dict[str, Any]) -> dict[str, Any]:
        stmt = select(ModerationSetting).where(ModerationSetting.group_id == group_id)
        settings = (await self.session.execute(stmt)).scalar_one_or_none()
        if not settings:
            settings = ModerationSetting(group_id=group_id)
            self.session.add(settings)

        for key, value in data.items():
            if value is not None and hasattr(settings, key):
                setattr(settings, key, value)
        
        await self.session.commit()
        return await self.get_settings(group_id)

    async def list_events(self, group_id: int, limit: int = 100) -> list[dict[str, Any]]:
        stmt = (
            select(ModerationEvent)
            .where(ModerationEvent.group_id == group_id)
            .order_by(ModerationEvent.created_at.desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [
            {
                "id": row.id,
                "message_id": row.message_id,
                "user_id": row.user_id,
                "username": row.username,
                "text_preview": row.text_preview,
                "category": row.category,
                "confidence": row.confidence,
                "reason": row.reason,
                "matched_signals": row.matched_signals,
                "recommended_action": row.recommended_action,
                "action_taken": row.action_taken,
                "dry_run": row.dry_run,
                "status": row.status,
                "error_message": row.error_message,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
