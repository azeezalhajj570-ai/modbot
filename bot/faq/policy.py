"""FAQ policy logic to decide actions based on matches and settings."""

from strenum import StrEnum
from typing import Any, Optional
from bot.faq.matcher import MatchResult
from bot.db.models.faq import FAQMode

class FAQAction(StrEnum):
    SKIP = "skip"
    LOG_UNANSWERED = "log_unanswered"
    SUGGEST_TO_ADMIN = "suggest_to_admin"
    AUTO_REPLY = "auto_reply"

def decide_faq_action(
    match_result: MatchResult, 
    settings: Any, 
    is_admin: bool = False,
    global_enabled: bool = True
) -> FAQAction:
    """
    Decide what action to take based on match results and group settings.
    """
    if not global_enabled:
        return FAQAction.SKIP
        
    if not settings or not settings.enabled:
        return FAQAction.SKIP
        
    # Skip admins if not explicitly allowed (default skip for now as per instructions)
    # "If sender is admin and settings do not allow answering admins: skip."
    # We don't have a specific setting for "answering admins" in FAQSettings yet, 
    # so we assume skip for safety if requested.
    if is_admin:
        return FAQAction.SKIP
        
    # If no match
    if not match_result.faq_entry_id or match_result.confidence < settings.suggestion_threshold:
        if settings.log_unanswered_questions:
            return FAQAction.LOG_UNANSWERED
        return FAQAction.SKIP
        
    # Safe mode logic: suggest_to_admin unless admin explicitly enabled auto_reply
    # and confidence is high enough.
    
    effective_mode = settings.default_mode
    if settings.safe_mode and effective_mode == FAQMode.AUTO_REPLY:
        # In safe mode, we downgrade AUTO_REPLY to ADMIN_SUGGESTION
        # unless we have a specific override (which we don't yet).
        effective_mode = FAQMode.ADMIN_SUGGESTION
        
    if match_result.confidence >= settings.auto_reply_threshold:
        if effective_mode == FAQMode.AUTO_REPLY:
            return FAQAction.AUTO_REPLY
        elif effective_mode == FAQMode.ADMIN_SUGGESTION:
            return FAQAction.SUGGEST_TO_ADMIN
            
    if match_result.confidence >= settings.suggestion_threshold:
        if effective_mode != FAQMode.DISABLED:
            return FAQAction.SUGGEST_TO_ADMIN
            
    return FAQAction.SKIP
