"""Actions to execute for FAQ matches."""

from dataclasses import dataclass
from typing import Optional
from bot.faq.policy import FAQAction

@dataclass
class FAQActionResult:
    action: FAQAction
    faq_entry_id: Optional[int] = None
    answer: Optional[str] = None
    confidence: float = 0.0
    error: Optional[str] = None

def format_public_reply(answer: str) -> str:
    """Format the answer for public group reply."""
    return f"{answer}\n\n— Answered from group FAQ"

def format_admin_suggestion(question: str, matched_question: str, answer: str, confidence: float) -> str:
    """Format the suggestion for admin review."""
    return (
        f"🤖 *FAQ Suggestion*\n\n"
        f"*User asked:* {question}\n"
        f"*Matched with:* {matched_question}\n"
        f"*Confidence:* {confidence:.2f}\n\n"
        f"*Suggested Answer:*\n{answer}\n\n"
        f"Should I send this answer?"
    )
