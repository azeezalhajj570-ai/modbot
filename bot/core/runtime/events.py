from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from strenum import StrEnum
from uuid import uuid4
from typing import Any


class RuntimeEventType(StrEnum):
    MODERATION_MESSAGE_FLAGGED = "moderation.message_flagged"
    MODERATION_WARNING_TRIGGERED = "moderation.warning_triggered"
    MODERATION_USER_ACTION_REQUESTED = "moderation.user_action_requested"
    MODERATION_WARNING_REVIEW_REQUESTED = "moderation.warning_review_requested"
    AUTOMATION_ACTIVITY_RECORDED = "automation.activity_recorded"
    AUTOMATION_KEYWORD_REPLY_REQUESTED = "automation.keyword_reply_requested"
    AUTOMATION_NOTIFY_DESTINATION_REQUESTED = "automation.notify_destination_requested"
    AUTOMATION_TASK_FOLLOW_UP_REQUESTED = "automation.task_follow_up_requested"
    AUTOMATION_SCHEDULED_MESSAGE_DUE = "automation.scheduled_message_due"


@dataclass
class RuntimeEvent:
    name: str
    group_id: int
    actor_user_id: int | None
    subject_type: str | None = None
    subject_id: str | None = None
    source: str = "runtime"
    correlation_id: str = field(default_factory=lambda: uuid4().hex)
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
