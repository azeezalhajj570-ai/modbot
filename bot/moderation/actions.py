from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot
from bot.core.runtime.moderation import FlaggedMessageModerationRequest, ModerationRuntimeService
from bot.moderation.schemas import ModerationAction, ModerationDecision
from bot.db.models.moderation import ModerationSetting

logger = logging.getLogger(__name__)

async def execute_moderation_action(
    session: Any,
    bot: Bot,
    group_id: int,
    chat_id: int,
    message_id: int,
    user_id: int | None,
    action: ModerationAction,
    decision: ModerationDecision,
    settings: ModerationSetting,
) -> str:
    if action == ModerationAction.ALLOW:
        return "allowed"

    if settings.dry_run:
        logger.info(
            "moderation_dry_run",
            group_id=group_id,
            chat_id=chat_id,
            message_id=message_id,
            intended_action=action,
        )
        return "dry_run"

    runtime = ModerationRuntimeService(session)
    
    try:
        if action == ModerationAction.DELETE:
            await runtime.enforce_flagged_message(
                FlaggedMessageModerationRequest(
                    group_id=group_id,
                    chat_id=chat_id,
                    message_id=message_id,
                    target_user_id=user_id,
                    source="ai_spam_detection",
                    reason=decision.reason,
                    score=decision.confidence,
                    delete_log_action="delete_spam",
                    metadata={
                        "category": decision.category,
                        "matched_signals": decision.matched_signals,
                    }
                ),
                bot=bot
            )
            return "deleted"
        
        elif action == ModerationAction.WARN:
            # Reusing enforce_flagged_warning logic
            from bot.core.runtime.moderation import FlaggedWarningModerationRequest
            if user_id:
                await runtime.enforce_flagged_warning(
                    FlaggedWarningModerationRequest(
                        group_id=group_id,
                        chat_id=chat_id,
                        target_user_id=user_id,
                        source="ai_spam_detection",
                        reason=decision.reason,
                        score=decision.confidence,
                        notice_key="spam_warning",
                        log_action="warn_spam",
                        metadata={
                            "category": decision.category,
                            "matched_signals": decision.matched_signals,
                            "message_id": message_id,
                        }
                    ),
                    bot=bot
                )
            return "warned"
        
        elif action == ModerationAction.MUTE:
            # We can use apply_action for direct mute
            if user_id:
                await runtime.apply_action(
                    group_id=group_id,
                    actor_user_id=None, # System action
                    user_id=user_id,
                    action="mute",
                    reason=f"{decision.category}: {decision.reason}",
                )
            return "muted"
        
        elif action == ModerationAction.BAN:
            if user_id:
                await runtime.apply_action(
                    group_id=group_id,
                    actor_user_id=None,
                    user_id=user_id,
                    action="ban",
                    reason=f"{decision.category}: {decision.reason}",
                )
            return "banned"
        
        elif action == ModerationAction.REVIEW:
            # Already logged as "review" status in events table
            return "review"

    except Exception as exc:
        logger.error("moderation_action_failed", exc_info=exc)
        return f"error: {str(exc)}"

    return "unknown"
