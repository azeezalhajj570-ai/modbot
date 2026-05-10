from __future__ import annotations

import re
from typing import Protocol

from bot.moderation.schemas import ModerationAction, ModerationCategory, ModerationDecision


class SpamScamClassifier(Protocol):
    async def classify(self, text: str) -> ModerationDecision:
        ...


class HeuristicSpamScamClassifier:
    ARABIC_SCAM_SIGNALS = {
        r"اربح|أرباح|ربح": ModerationCategory.INVESTMENT_SCAM,
        r"ربح مضمون|مضمون 100%": ModerationCategory.INVESTMENT_SCAM,
        r"دخل يومي": ModerationCategory.INVESTMENT_SCAM,
        r"استثمار": ModerationCategory.INVESTMENT_SCAM,
        r"تداول": ModerationCategory.INVESTMENT_SCAM,
        r"توصيات": ModerationCategory.CRYPTO_SCAM,
        r"اشترك": ModerationCategory.ARABIC_AD,
        r"تواصل خاص": ModerationCategory.ARABIC_AD,
        r"فرصة لا تعوض": ModerationCategory.INVESTMENT_SCAM,
        r"بدون رأس مال": ModerationCategory.INVESTMENT_SCAM,
        r"ضاعف أرباحك": ModerationCategory.INVESTMENT_SCAM,
        r"بوت استثمار": ModerationCategory.INVESTMENT_SCAM,
        r"قناة توصيات": ModerationCategory.CRYPTO_SCAM,
        r"انضم الآن": ModerationCategory.ARABIC_AD,
        r"رابط التسجيل": ModerationCategory.LINK_SPAM,
    }

    ENGLISH_SCAM_SIGNALS = {
        r"guaranteed profit": ModerationCategory.INVESTMENT_SCAM,
        r"daily profit": ModerationCategory.INVESTMENT_SCAM,
        r"double your money": ModerationCategory.INVESTMENT_SCAM,
        r"risk free investment": ModerationCategory.INVESTMENT_SCAM,
        r"crypto signal": ModerationCategory.CRYPTO_SCAM,
        r"investment opportunity": ModerationCategory.INVESTMENT_SCAM,
        r"click here": ModerationCategory.LINK_SPAM,
        r"join now": ModerationCategory.ARABIC_AD,
        r"limited offer": ModerationCategory.ARABIC_AD,
    }

    SUSPICIOUS_LINKS_RE = re.compile(
        r"(bit\.ly|t\.co|tinyurl|cutt\.ly|rebrand\.ly|t\.me/(\+[a-zA-Z0-9_-]+|joinchat/))",
        re.IGNORECASE
    )

    async def classify(self, text: str) -> ModerationDecision:
        if not text:
            return ModerationDecision(ModerationCategory.SAFE, 0.0, "empty_text")

        lowered = text.lower()
        matched_signals = []
        category = ModerationCategory.SAFE
        max_confidence = 0.0

        # Check English signals
        for pattern, cat in self.ENGLISH_SCAM_SIGNALS.items():
            if re.search(pattern, lowered):
                matched_signals.append(f"en:{pattern}")
                category = cat
                max_confidence = max(max_confidence, 0.85)

        # Check Arabic signals
        for pattern, cat in self.ARABIC_SCAM_SIGNALS.items():
            if re.search(pattern, text):
                matched_signals.append(f"ar:{pattern}")
                category = cat
                max_confidence = max(max_confidence, 0.9)

        # Check suspicious links
        link_matches = self.SUSPICIOUS_LINKS_RE.findall(text)
        if link_matches:
            matched_signals.append("suspicious_link")
            category = ModerationCategory.PHISHING_LINK if category == ModerationCategory.SAFE else category
            max_confidence = max(max_confidence, 0.8)

        if not matched_signals:
            return ModerationDecision(ModerationCategory.SAFE, 0.0, "no_signals")

        # Increase confidence if multiple signals found
        if len(matched_signals) > 1:
            max_confidence = min(max_confidence + 0.1, 0.99)

        recommended_action = ModerationAction.REVIEW
        if max_confidence >= 0.92:
            recommended_action = ModerationAction.DELETE

        return ModerationDecision(
            category=category,
            confidence=max_confidence,
            reason="heuristic_match",
            matched_signals=matched_signals,
            recommended_action=recommended_action,
        )
