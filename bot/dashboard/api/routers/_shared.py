from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from bot.db.models import Agent


class PluginToggleRequest(BaseModel):
    group_id: int
    plugin_name: str
    enabled: bool = True


class SettingsPatchRequest(BaseModel):
    settings: dict[str, bool | int | str] = Field(default_factory=dict)


class WarningPatchRequest(BaseModel):
    user_id: int
    reason: str | None = None
    count: int = 1


class MemberRoleUpdateRequest(BaseModel):
    role: str = Field(pattern="^(owner|super_admin|admin|moderator)$")


class JoinRequestActionRequest(BaseModel):
    action: str = Field(pattern="^(approve|decline)$")
    reason: str | None = Field(default=None, max_length=500)


class ModerationActionRequest(BaseModel):
    user_id: int = Field(ge=1)
    action: str = Field(pattern="^(approve|warn|mute|ban|unmute|unban)$")
    reason: str | None = Field(default=None, max_length=500)
    count: int = Field(default=1, ge=1, le=10)


class ModerationSettingsUpdateRequest(BaseModel):
    enabled: bool | None = None
    safe_mode: bool | None = None
    dry_run: bool | None = None
    default_action: str | None = Field(default=None, pattern="^(allow|review|delete|warn|mute|ban)$")
    review_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    auto_delete_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    mute_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    ban_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    action_for_arabic_ads: str | None = Field(default=None, pattern="^(allow|review|delete|warn|mute|ban)$")
    action_for_investment_scam: str | None = Field(default=None, pattern="^(allow|review|delete|warn|mute|ban)$")
    action_for_crypto_scam: str | None = Field(default=None, pattern="^(allow|review|delete|warn|mute|ban)$")
    action_for_phishing_link: str | None = Field(default=None, pattern="^(allow|review|delete|warn|mute|ban)$")
    action_for_link_spam: str | None = Field(default=None, pattern="^(allow|review|delete|warn|mute|ban)$")
    action_for_repeated_promo: str | None = Field(default=None, pattern="^(allow|review|delete|warn|mute|ban)$")
    allowlisted_domains: list[str] | None = None
    blocked_domains: list[str] | None = None
    allowlisted_user_ids: list[int] | None = None
    muted_duration_seconds: int | None = Field(default=None, ge=0)


class AgentLinkRequest(BaseModel):
    group_id: int | None = None
    external_account_id: str | None = Field(default=None, min_length=1, max_length=255)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    phone_number: str | None = Field(default=None, min_length=1, max_length=32)
    telegram_user_id: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentUpdateRequest(BaseModel):
    external_account_id: str | None = Field(default=None, min_length=1, max_length=255)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    phone_number: str | None = Field(default=None, min_length=1, max_length=32)
    telegram_user_id: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentJobCreateRequest(BaseModel):
    job_type: str = Field(min_length=1, max_length=100)
    job_payload: dict[str, Any] = Field(default_factory=dict)


class AgentSafetyUpdateRequest(BaseModel):
    max_actions_per_hour: int | None = Field(default=None, ge=1, le=1000)
    max_messages_per_day: int | None = Field(default=None, ge=1, le=5000)
    min_delay_seconds: float | None = Field(default=None, ge=0.0, le=300.0)
    cooldown_minutes: int | None = Field(default=None, ge=1, le=1440)
    safety_mode_enabled: bool | None = None
    safety_mode_hours: int | None = Field(default=None, ge=0, le=720)


class LeadUpdateRequest(BaseModel):
    status: str | None = Field(default=None, pattern="^(new|contacted|interested|converted|junk|dismissed)$")
    assigned_to: int | None = None
    contact_info: str | None = Field(default=None, max_length=512)
    notes: str | None = Field(default=None, max_length=5000)
    lead_label: str | None = Field(default=None, max_length=64)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class AgentLoginStartRequest(BaseModel):
    group_id: int | None = None
    agent_id: int | None = Field(default=None, ge=1)
    phone_number: str = Field(min_length=1, max_length=32)


class AgentLoginCodeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32)


class AgentLoginPasswordRequest(BaseModel):
    password: str = Field(min_length=1, max_length=255)


class TaskAssignmentRequest(BaseModel):
    assignment_id: str | None = None
    task_key: str = Field(min_length=1, max_length=100)
    executor_type: str = Field(min_length=1, max_length=16)
    enabled: bool = True
    conditions: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    agent_id: int | None = None
    group_ids: list[int] = Field(default_factory=list)
    group_tg_ids: list[int] = Field(default_factory=list)
    group_titles: list[str] = Field(default_factory=list)


class ScheduledMessageRequest(BaseModel):
    text: str = Field(min_length=1)
    schedule: str = Field(min_length=1, max_length=100)
    delete_after_seconds: int | None = Field(default=None, ge=0)


class TaskAssignmentPatchRequest(BaseModel):
    task_key: str | None = Field(default=None, min_length=1, max_length=100)
    executor_type: str | None = Field(default=None, min_length=1, max_length=16)
    enabled: bool | None = None
    conditions: dict[str, Any] | None = None
    config: dict[str, Any] | None = None
    agent_id: int | None = None
    group_ids: list[int] | None = None
    group_tg_ids: list[int] | None = None
    group_titles: list[str] | None = None


class ScheduledMessagePatchRequest(BaseModel):
    text: str | None = Field(default=None, min_length=1)
    schedule: str | None = Field(default=None, min_length=1, max_length=100)
    delete_after_seconds: int | None = None


class NotificationFollowUpRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class LanguageUpdateRequest(BaseModel):
    language_code: str = Field(pattern="^(en|ar)$")


class EmailPasswordLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=255)


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=255)


class AccessGateUpdateRequest(BaseModel):
    required_group_tg_ids: list[int] = Field(default_factory=list)


class RedeemCodeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)


class BotInstallTarget(BaseModel):
    tg_group_id: int
    title: str = Field(min_length=1, max_length=255)


class BotInstallLinkRequest(BaseModel):
    group_ids: list[int] = Field(default_factory=list, min_length=1, max_length=50)
    groups: list[BotInstallTarget] = Field(default_factory=list, max_length=50)
    permissions: list[str] = Field(default_factory=list, max_length=20)


BOT_INSTALL_PERMISSION_KEYS = {
    "change_info",
    "delete_messages",
    "restrict_members",
    "invite_users",
    "pin_messages",
    "manage_topics",
    "manage_video_chats",
    "promote_members",
}


def serialize_agent(agent: Agent) -> dict[str, Any]:
    return {
        "id": agent.id,
        "group_id": agent.group_id,
        "linked_by_user_id": agent.linked_by_user_id,
        "phone_number": agent.phone_number,
        "external_account_id": agent.external_account_id,
        "status": agent.status,
        "auth_state": agent.auth_state,
        "metadata": agent.details,
        "max_actions_per_hour": agent.max_actions_per_hour,
        "max_messages_per_day": agent.max_messages_per_day,
        "min_delay_seconds": agent.min_delay_seconds,
        "cooldown_minutes": agent.cooldown_minutes,
        "safety_mode_enabled": agent.safety_mode_enabled,
        "safety_mode_until": agent.safety_mode_until.isoformat() if agent.safety_mode_until else None,
    }


def schedule_delay_seconds(send_at: str) -> int:
    return max(0, int((datetime.fromisoformat(send_at) - datetime.utcnow()).total_seconds()))


def tally_recent_activity(rows: list[Any]) -> dict[str, int]:
    message_activity: dict[str, int] = defaultdict(int)
    for row in rows:
        date_key = row.created_at.date().isoformat() if row.created_at else "unknown"
        message_activity[date_key] += 1
    return dict(sorted(message_activity.items()))


__all__ = [
    "AccessGateUpdateRequest",
    "AgentJobCreateRequest",
    "AgentSafetyUpdateRequest",
    "AgentLinkRequest",
    "AgentLoginCodeRequest",
    "AgentLoginPasswordRequest",
    "AgentLoginStartRequest",
    "AgentUpdateRequest",
    "BOT_INSTALL_PERMISSION_KEYS",
    "BotInstallLinkRequest",
    "BotInstallTarget",
    "EmailPasswordLoginRequest",
    "JoinRequestActionRequest",
    "LanguageUpdateRequest",
    "MemberRoleUpdateRequest",
    "ModerationActionRequest",
    "ModerationSettingsUpdateRequest",
    "NotificationFollowUpRequest",
    "PluginToggleRequest",
    "RedeemCodeRequest",
    "RegisterRequest",
    "ScheduledMessagePatchRequest",
    "ScheduledMessageRequest",
    "SettingsPatchRequest",
    "TaskAssignmentPatchRequest",
    "TaskAssignmentRequest",
    "WarningPatchRequest",
    "schedule_delay_seconds",
    "serialize_agent",
    "tally_recent_activity",
]
