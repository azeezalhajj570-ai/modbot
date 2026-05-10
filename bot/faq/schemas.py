"""Pydantic schemas for FAQ API."""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict
from bot.db.models.faq import FAQMode, FAQSourceType, FAQInteractionStatus, UnansweredQuestionStatus

class FAQSettingsSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    enabled: bool = False
    safe_mode: bool = True
    default_mode: FAQMode = FAQMode.ADMIN_SUGGESTION
    auto_reply_threshold: float = 0.85
    suggestion_threshold: float = 0.60
    max_replies_per_user_per_hour: int = 3
    max_replies_per_group_per_hour: int = 20
    answer_cooldown_seconds: int = 60
    log_unanswered_questions: bool = True
    require_admin_approved_sources: bool = True


class FAQEntryCreate(BaseModel):
    question: str
    answer: str
    keywords: List[str] = []
    language: Optional[str] = None
    category: Optional[str] = None
    source_type: FAQSourceType = FAQSourceType.MANUAL
    source_ref: Optional[str] = None
    enabled: bool = True

class FAQEntryUpdate(BaseModel):
    question: Optional[str] = None
    answer: Optional[str] = None
    keywords: Optional[List[str]] = None
    language: Optional[str] = None
    category: Optional[str] = None
    enabled: Optional[bool] = None

class FAQEntrySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    group_id: int
    question: str
    answer: str
    keywords: List[str]
    language: Optional[str]
    category: Optional[str]
    source_type: FAQSourceType
    source_ref: Optional[str]
    enabled: bool
    created_at: datetime
    updated_at: datetime


class FAQInteractionSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    group_id: int
    message_id: int
    user_id: int
    username: Optional[str]
    user_question_preview: str
    matched_faq_entry_id: Optional[int]
    confidence: float
    mode: str
    answer_preview: Optional[str]
    status: FAQInteractionStatus
    created_at: datetime


class UnansweredQuestionSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    group_id: int
    message_id: int
    user_id: int
    username: Optional[str]
    question_preview: str
    normalized_question: str
    frequency_count: int
    status: UnansweredQuestionStatus
    created_at: datetime
    last_seen_at: datetime


class FAQTestMatchRequest(BaseModel):
    question: str

class FAQTestMatchResponse(BaseModel):
    matched: bool
    confidence: float
    entry_id: Optional[int] = None
    answer: Optional[str] = None

class FAQAnswerPayload(BaseModel):
    answer: str
