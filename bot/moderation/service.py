from __future__ import annotations

import logging
import re
from typing import Any

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from bot.config import get_settings
from bot.db.models import Group
from bot.db.models.moderation import ModerationEvent, ModerationSetting
from bot.moderation.actions import execute_moderation_action
from bot.moderation.policy import decide_action
from bot.moderation.repeated_messages import RepeatedMessageDetector
from bot.moderation.schemas import ModerationAction, ModerationCategory, ModerationDecision
from bot.moderation.spam_detection import HeuristicSpamScamClassifier

logger = logging.getLogger(__name__)


class ModerationService:
    def __init__(
        self,
        session: AsyncSession,
        redis_client: Any | None = None,
        bot: Bot | None = None,
    ) -> None:
        self.session = session
        self.redis = redis_client
        self.bot = bot
        self.heuristic = HeuristicSpamScamClassifier()
        self.repeats = RepeatedMessageDetector(redis_client=redis_client)

    async def _get_or_create_settings(self, group_id: int) -> ModerationSetting:
        stmt = select(ModerationSetting).where(ModerationSetting.group_id == group_id)
        settings = (await self.session.execute(stmt)).scalar_one_or_none()
        if not settings:
            settings = ModerationSetting(group_id=group_id)
            self.session.add(settings)
            try:
                await self.session.flush()
            except IntegrityError:
                await self.session.rollback()
                stmt = select(ModerationSetting).where(ModerationSetting.group_id == group_id)
                settings = (await self.session.execute(stmt)).scalar_one()
        return settings

    async def process_message(
        self,
        chat_id: int,
        message_id: int,
        user_id: int | None,
        username: str | None,
        text: str,
        context_overrides: dict[str, Any] | None = None,
    ) -> ModerationDecision | None:
        settings = get_settings()
        global_enabled = getattr(settings, "ai_spam_detection_enabled", False)
        
        # 1. Resolve internal group ID
        group_stmt = select(Group).where(Group.tg_group_id == chat_id)
        group = (await self.session.execute(group_stmt)).scalar_one_or_none()
        if not group:
            return None

        # 2. Get moderation settings
        mod_settings = await self._get_or_create_settings(group.id)
        
        # 3. Fast exit if disabled
        if not global_enabled or not mod_settings.enabled:
            return None

        # 4. Classification
        heuristic_decision = await self.heuristic.classify(text)
        
        # Check repeats
        repeat_decision = ModerationDecision(ModerationCategory.SAFE, 0.0, "clean")
        if user_id:
            repeat_decision = await self.repeats.check(group.id, user_id, text)

        # Combine decisions
        if repeat_decision.category != ModerationCategory.SAFE and repeat_decision.confidence > heuristic_decision.confidence:
            final_decision = repeat_decision
        else:
            final_decision = heuristic_decision

        # Optional LLM fallback if uncertainty exists and configured
        
        # Extract domains for policy logic
        detected_domains = []
        try:
            detected_domains = re.findall(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9][a-z0-9-]{0,61}[a-z0-9]", text.lower())
        except Exception:
            pass

        # 5. Policy Check
        policy_context = {
            "global_enabled": global_enabled,
            "sender_user_id": user_id,
            "sender_is_admin": context_overrides.get("is_admin", False) if context_overrides else False,
            "sender_is_owner": context_overrides.get("is_owner", False) if context_overrides else False,
            "detected_domains": detected_domains,
        }
        
        action = decide_action(final_decision, mod_settings, policy_context)
        
        # 6. Execute Action
        status = "allowed"
        error_message = None
        if action != ModerationAction.ALLOW and self.bot:
            status = await execute_moderation_action(
                self.session,
                self.bot,
                group.id,
                chat_id,
                message_id,
                user_id,
                action,
                final_decision,
                mod_settings,
            )
            if status.startswith("error:"):
                error_message = status
                status = "error"

        # 7. Log Event (Idempotent)
        await self._log_event(
            group_id=group.id,
            message_id=message_id,
            user_id=user_id,
            username=username,
            text_preview=text[:500],
            decision=final_decision,
            action_taken=action,
            dry_run=mod_settings.dry_run,
            status=status,
            error_message=error_message,
        )
        
        await self.session.flush()
        return final_decision

    async def _log_event(
        self,
        group_id: int,
        message_id: int,
        user_id: int | None,
        username: str | None,
        text_preview: str,
        decision: ModerationDecision,
        action_taken: ModerationAction,
        dry_run: bool,
        status: str,
        error_message: str | None = None,
    ) -> None:
        data = {
            "group_id": group_id,
            "message_id": message_id,
            "user_id": user_id,
            "username": username,
            "text_preview": text_preview,
            "category": decision.category,
            "confidence": decision.confidence,
            "reason": decision.reason,
            "matched_signals": decision.matched_signals,
            "recommended_action": decision.recommended_action,
            "action_taken": action_taken,
            "dry_run": dry_run,
            "status": status,
            "error_message": error_message,
        }

        # Handle idempotency via dialect-specific UPSERT
        if self.session.bind.dialect.name == "postgresql":
            stmt = pg_insert(ModerationEvent).values(**data)
            stmt = stmt.on_conflict_do_update(
                index_elements=["group_id", "message_id"],
                set_={k: v for k, v in data.items() if k not in {"group_id", "message_id"}},
            )
        else:
            stmt = sqlite_insert(ModerationEvent).values(**data)
            stmt = stmt.on_conflict_do_update(
                index_elements=["group_id", "message_id"],
                set_={k: v for k, v in data.items() if k not in {"group_id", "message_id"}},
            )

        await self.session.execute(stmt)
