"""FAQ service for managing entries and processing questions."""

import logging
from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Any

from sqlalchemy import select, update, delete, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.db.models.faq import (
    FAQSettings, FAQEntry, FAQInteraction, UnansweredQuestion,
    FAQMode, FAQInteractionStatus, UnansweredQuestionStatus
)
from bot.faq.matcher import DeterministicFAQMatcher, MatchResult, normalize_text, get_question_hash
from bot.faq.question_detection import is_question
from bot.faq.policy import decide_faq_action, FAQAction
from bot.faq.actions import FAQActionResult

logger = logging.getLogger(__name__)

class FAQService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.matcher = DeterministicFAQMatcher()

    async def get_settings(self, group_id: int) -> FAQSettings:
        """Get or create FAQ settings for a group."""
        stmt = select(FAQSettings).where(FAQSettings.group_id == group_id)
        result = await self.session.execute(stmt)
        settings = result.scalar_one_or_none()
        
        if not settings:
            settings = FAQSettings(group_id=group_id)
            self.session.add(settings)
            await self.session.flush()
            
        return settings

    async def update_settings(self, group_id: int, **kwargs) -> FAQSettings:
        """Update FAQ settings for a group."""
        settings = await self.get_settings(group_id)
        for key, value in kwargs.items():
            if hasattr(settings, key):
                setattr(settings, key, value)
        await self.session.flush()
        return settings

    async def add_entry(self, group_id: int, **kwargs) -> FAQEntry:
        """Add a new FAQ entry."""
        entry = FAQEntry(group_id=group_id, **kwargs)
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def get_entries(self, group_id: int, enabled_only: bool = False) -> List[FAQEntry]:
        """Get all FAQ entries for a group."""
        stmt = select(FAQEntry).where(FAQEntry.group_id == group_id)
        if enabled_only:
            stmt = stmt.where(FAQEntry.enabled == True)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete_entry(self, group_id: int, entry_id: int) -> bool:
        """Delete an FAQ entry."""
        stmt = delete(FAQEntry).where(and_(FAQEntry.group_id == group_id, FAQEntry.id == entry_id))
        result = await self.session.execute(stmt)
        return result.rowcount > 0

    async def process_message(
        self, 
        group_id: int, 
        message_id: int, 
        user_id: int, 
        username: Optional[str],
        text: str,
        is_admin: bool = False,
        global_enabled: bool = False
    ) -> Optional[FAQActionResult]:
        """
        Process an incoming message and decide on FAQ actions.
        """
        if not text or len(text.strip()) < 3:
            return None

        settings = await self.get_settings(group_id)
        
        # 1. Question detection
        if not is_question(text):
            return None

        # 2. Matching
        entries = await self.get_entries(group_id, enabled_only=True)
        match_result = self.matcher.match(text, entries)
        
        # 3. Policy
        action = decide_faq_action(
            match_result, 
            settings, 
            is_admin=is_admin, 
            global_enabled=global_enabled
        )
        
        # 4. Rate limiting (simple in-memory or DB-based)
        if action in [FAQAction.AUTO_REPLY, FAQAction.SUGGEST_TO_ADMIN]:
            if await self._is_rate_limited(group_id, user_id, settings):
                action = FAQAction.SKIP

        # 5. Execute & Log
        result = FAQActionResult(
            action=action,
            faq_entry_id=match_result.faq_entry_id,
            answer=match_result.answer,
            confidence=match_result.confidence
        )
        
        await self._log_interaction(
            group_id, message_id, user_id, username, text, match_result, action, result
        )
        
        if action == FAQAction.LOG_UNANSWERED:
            await self._log_unanswered_question(
                group_id, message_id, user_id, username, text, match_result
            )
            
        return result

    async def _is_rate_limited(self, group_id: int, user_id: int, settings: FAQSettings) -> bool:
        """Check if rate limits are exceeded."""
        one_hour_ago = datetime.utcnow() - timedelta(hours=1)
        
        # User limit
        stmt_user = select(func.count(FAQInteraction.id)).where(
            and_(
                FAQInteraction.group_id == group_id,
                FAQInteraction.user_id == user_id,
                FAQInteraction.status == FAQInteractionStatus.SENT,
                FAQInteraction.created_at >= one_hour_ago
            )
        )
        user_count = (await self.session.execute(stmt_user)).scalar() or 0
        if user_count >= settings.max_replies_per_user_per_hour:
            return True
            
        # Group limit
        stmt_group = select(func.count(FAQInteraction.id)).where(
            and_(
                FAQInteraction.group_id == group_id,
                FAQInteraction.status == FAQInteractionStatus.SENT,
                FAQInteraction.created_at >= one_hour_ago
            )
        )
        group_count = (await self.session.execute(stmt_group)).scalar() or 0
        if group_count >= settings.max_replies_per_group_per_hour:
            return True
            
        return False

    async def _log_interaction(
        self,
        group_id: int,
        message_id: int,
        user_id: int,
        username: Optional[str],
        text: str,
        match_result: MatchResult,
        action: FAQAction,
        result: FAQActionResult
    ):
        """Log the FAQ interaction for audit and idempotency."""
        status_map = {
            FAQAction.SKIP: FAQInteractionStatus.SKIPPED,
            FAQAction.LOG_UNANSWERED: FAQInteractionStatus.UNANSWERED,
            FAQAction.SUGGEST_TO_ADMIN: FAQInteractionStatus.SUGGESTED,
            FAQAction.AUTO_REPLY: FAQInteractionStatus.SENT
        }
        
        interaction = FAQInteraction(
            group_id=group_id,
            message_id=message_id,
            user_id=user_id,
            username=username,
            user_question_preview=text[:255],
            matched_faq_entry_id=match_result.faq_entry_id,
            confidence=match_result.confidence,
            mode=action.value,
            answer_preview=match_result.answer[:255] if match_result.answer else None,
            status=status_map.get(action, FAQInteractionStatus.SKIPPED),
            error_message=result.error
        )
        self.session.add(interaction)
        await self.session.flush()

    async def _log_unanswered_question(
        self,
        group_id: int,
        message_id: int,
        user_id: int,
        username: Optional[str],
        text: str,
        match_result: MatchResult
    ):
        """Log an unanswered question with deduplication."""
        norm_q = match_result.normalized_question or normalize_text(text)
        q_hash = get_question_hash(norm_q)
        
        stmt = select(UnansweredQuestion).where(
            and_(
                UnansweredQuestion.group_id == group_id,
                UnansweredQuestion.normalized_question_hash == q_hash
            )
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()
        
        if existing:
            existing.frequency_count += 1
            existing.last_seen_at = datetime.utcnow()
            if existing.status == UnansweredQuestionStatus.IGNORED:
                existing.status = UnansweredQuestionStatus.NEW
        else:
            unanswered = UnansweredQuestion(
                group_id=group_id,
                message_id=message_id,
                user_id=user_id,
                username=username,
                question_preview=text[:255],
                normalized_question=norm_q,
                normalized_question_hash=q_hash,
                status=UnansweredQuestionStatus.NEW
            )
            self.session.add(unanswered)
            
        await self.session.flush()

    async def get_unanswered_questions(self, group_id: int) -> List[UnansweredQuestion]:
        """Get unanswered questions for a group."""
        stmt = select(UnansweredQuestion).where(
            and_(
                UnansweredQuestion.group_id == group_id,
                UnansweredQuestion.status == UnansweredQuestionStatus.NEW
            )
        ).order_by(UnansweredQuestion.frequency_count.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def convert_to_faq(self, group_id: int, question_id: int, answer: str) -> FAQEntry:
        """Convert an unanswered question to an FAQ entry."""
        stmt = select(UnansweredQuestion).where(
            and_(
                UnansweredQuestion.group_id == group_id,
                UnansweredQuestion.id == question_id
            )
        )
        result = await self.session.execute(stmt)
        unanswered = result.scalar_one_or_none()
        
        if not unanswered:
            raise ValueError("Unanswered question not found")
            
        entry = await self.add_entry(
            group_id=group_id,
            question=unanswered.question_preview,
            answer=answer,
            source_type="manual"
        )
        
        unanswered.status = UnansweredQuestionStatus.CONVERTED_TO_FAQ
        await self.session.flush()
        return entry
