"""Domain-organized SQLAlchemy models."""

from strenum import StrEnum

from bot.db.base import Base
from bot.db.models.access import GroupAccessRequirement, PrivateAccessRequirement
from bot.db.models.agent import Agent, AgentJob, AgentLead, AgentNotification
from bot.db.models.audit import MembershipAuditLog, OwnerAuditLog
from bot.db.models.faq import (
    FAQEntry,
    FAQInteraction,
    FAQInteractionStatus,
    FAQMode,
    FAQSettings,
    FAQSourceType,
    UnansweredQuestion,
    UnansweredQuestionStatus,
)
from bot.db.models.group import Group, GroupAdminRole, GroupMember, GroupSetting, PluginEnabled
from bot.db.models.group_access import (
    GroupExpiryAction,
    GroupPaymentMode,
    GroupPaymentStatus,
    GroupSubscriber,
    GroupSubscriberStatus,
    GroupSubscriptionSettings,
    PaymentRecord,
    SubscriptionEvent,
    SubscriptionPlan,
)
from bot.db.models.join_request import JoinRequestApproval
from bot.db.models.messaging import (
    Automation,
    ChannelAccount,
    Contact,
    Conversation,
    Lead,
    Message,
    NotificationEvent,
    NotificationSettings,
    Skill,
    SkillRun,
    Tenant,
)
from bot.db.models.moderation import ModerationEvent, ModerationLog, ModerationSetting, Warning
from bot.db.models.scraper import GroupKnowledge, ScrapedConversation, ScrapedDailySummary, ScrapedGroup, ScrapedLead, ScrapedMember, ScrapedMessage
from bot.db.models.summary import DailyGroupSummary, GroupMessageActivity, GroupSummarySettings
from bot.db.models.subscription import PromotionCode, PromotionCodeRedemption, SubscriptionRequest
from bot.db.models.user import User


class AdminRole(StrEnum):
    OWNER = "owner"
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    MODERATOR = "moderator"


class SubscriptionStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DECLINED = "declined"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


__all__ = [
    "AdminRole",
    "Agent",
    "AgentJob",
    "AgentLead",
    "AgentNotification",
    "Automation",
    "Base",
    "ChannelAccount",
    "Contact",
    "Conversation",
    "DailyGroupSummary",
    "FAQEntry",
    "FAQInteraction",
    "FAQInteractionStatus",
    "FAQMode",
    "FAQSettings",
    "FAQSourceType",
    "Group",
    "GroupAccessRequirement",
    "GroupAdminRole",
    "GroupExpiryAction",
    "GroupKnowledge",
    "GroupMember",
    "GroupMessageActivity",
    "GroupPaymentMode",
    "GroupPaymentStatus",
    "GroupSetting",
    "GroupSubscriber",
    "GroupSubscriberStatus",
    "GroupSubscriptionSettings",
    "GroupSummarySettings",
    "JoinRequestApproval",
    "Lead",
    "MembershipAuditLog",
    "Message",
    "ModerationEvent",
    "ModerationLog",
    "ModerationSetting",
    "NotificationEvent",
    "NotificationSettings",
    "OwnerAuditLog",
    "PaymentRecord",
    "PrivateAccessRequirement",
    "PluginEnabled",
    "PromotionCode",
    "PromotionCodeRedemption",
    "ScrapedConversation",
    "ScrapedDailySummary",
    "ScrapedGroup",
    "ScrapedLead",
    "ScrapedMember",
    "ScrapedMessage",
    "Skill",
    "SkillRun",
    "SubscriptionEvent",
    "SubscriptionPlan",
    "SubscriptionRequest",
    "SubscriptionStatus",
    "Tenant",
    "UnansweredQuestion",
    "UnansweredQuestionStatus",
    "User",
    "Warning",
]
