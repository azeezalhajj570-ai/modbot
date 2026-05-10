from __future__ import annotations

from dataclasses import dataclass, field
from strenum import StrEnum


class ModerationCategory(StrEnum):
    SAFE = "safe"
    ARABIC_AD = "arabic_ad"
    INVESTMENT_SCAM = "investment_scam"
    CRYPTO_SCAM = "crypto_scam"
    PHISHING_LINK = "phishing_link"
    LINK_SPAM = "link_spam"
    REPEATED_PROMO = "repeated_promo"
    UNKNOWN_SUSPICIOUS = "unknown_suspicious"


class ModerationAction(StrEnum):
    ALLOW = "allow"
    REVIEW = "review"
    DELETE = "delete"
    WARN = "warn"
    MUTE = "mute"
    BAN = "ban"


@dataclass
class ModerationDecision:
    category: ModerationCategory
    confidence: float
    reason: str
    matched_signals: list[str] = field(default_factory=list)
    recommended_action: ModerationAction = ModerationAction.ALLOW
