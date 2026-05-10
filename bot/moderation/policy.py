from __future__ import annotations

from typing import Any

from bot.db.models.moderation import ModerationSetting
from bot.moderation.schemas import ModerationAction, ModerationCategory, ModerationDecision


def decide_action(
    decision: ModerationDecision,
    settings: ModerationSetting,
    context: dict[str, Any]
) -> ModerationAction:
    # 1. Check if global flag or group setting is disabled
    if not context.get("global_enabled", True):
        return ModerationAction.ALLOW
    if not settings.enabled:
        return ModerationAction.ALLOW

    # 2. Bypass admins/owners/allowlisted users
    if context.get("sender_is_admin", False) or context.get("sender_is_owner", False):
        return ModerationAction.ALLOW
    if context.get("sender_user_id") in (settings.allowlisted_user_ids or []):
        return ModerationAction.ALLOW

    # 3. Allow if confidence is below review threshold
    review_threshold = settings.review_threshold if settings.review_threshold is not None else 0.65
    
    # Check domains escalation/downgrade
    found_domains = context.get("detected_domains", [])
    blocked_match = any(d in (settings.blocked_domains or []) for d in found_domains)
    allowlisted_match = any(d in (settings.allowlisted_domains or []) for d in found_domains)

    if blocked_match:
        # Escalation: ensure at least REVIEW even if confidence is low
        if decision.confidence < review_threshold:
            decision.confidence = review_threshold
    
    if allowlisted_match:
        # Downgrade: never auto-delete/mute/ban
        if settings.safe_mode:
            return ModerationAction.REVIEW
        return ModerationAction.REVIEW # Force review for allowlisted domains instead of destructive action

    if decision.confidence < review_threshold:
        return ModerationAction.ALLOW

    # 4. Determine category-specific action override
    category_action = None
    if decision.category == ModerationCategory.ARABIC_AD:
        category_action = settings.action_for_arabic_ads
    elif decision.category == ModerationCategory.INVESTMENT_SCAM:
        category_action = settings.action_for_investment_scam
    elif decision.category == ModerationCategory.CRYPTO_SCAM:
        category_action = settings.action_for_crypto_scam
    elif decision.category == ModerationCategory.PHISHING_LINK:
        category_action = settings.action_for_phishing_link
    elif decision.category == ModerationCategory.LINK_SPAM:
        category_action = settings.action_for_link_spam
    elif decision.category == ModerationCategory.REPEATED_PROMO:
        category_action = settings.action_for_repeated_promo

    if category_action:
        return ModerationAction(category_action)

    # 5. Respect safe_mode: review suspicious content unless explicit action
    if settings.safe_mode:
        return ModerationAction.REVIEW

    # 6. Threshold-based actions (when safe_mode is False)
    ban_threshold = settings.ban_threshold if settings.ban_threshold is not None else 0.98
    mute_threshold = settings.mute_threshold if settings.mute_threshold is not None else 0.95
    auto_delete_threshold = settings.auto_delete_threshold if settings.auto_delete_threshold is not None else 0.92

    if decision.confidence >= ban_threshold:
        return ModerationAction.BAN
    if decision.confidence >= mute_threshold:
        return ModerationAction.MUTE
    if decision.confidence >= auto_delete_threshold:
        return ModerationAction.DELETE
    
    return ModerationAction.REVIEW
