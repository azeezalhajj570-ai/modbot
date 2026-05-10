from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "ActionExecutorRegistry": ("bot.core.runtime.executors", "ActionExecutorRegistry"),
    "AdminAutomationRuntimeService": ("bot.core.runtime.admin", "AdminAutomationRuntimeService"),
    "AddWarningAction": ("bot.core.runtime.actions", "AddWarningAction"),
    "AutomationRuntimeService": ("bot.core.runtime.automation", "AutomationRuntimeService"),
    "AuditEntry": ("bot.core.runtime.audit", "AuditEntry"),
    "AuditSink": ("bot.core.runtime.audit", "AuditSink"),
    "BanUserAction": ("bot.core.runtime.actions", "BanUserAction"),
    "ClearWarningsAction": ("bot.core.runtime.actions", "ClearWarningsAction"),
    "DeleteMessageAction": ("bot.core.runtime.actions", "DeleteMessageAction"),
    "GuardDecision": ("bot.core.runtime.guards", "GuardDecision"),
    "GuardPipeline": ("bot.core.runtime.guards", "GuardPipeline"),
    "GuardResult": ("bot.core.runtime.guards", "GuardResult"),
    "KeywordReplyRequest": ("bot.core.runtime.automation", "KeywordReplyRequest"),
    "MaybeMuteUserAction": ("bot.core.runtime.actions", "MaybeMuteUserAction"),
    "ModerationAction": ("bot.core.runtime.actions", "ModerationAction"),
    "ModerationLogAuditSink": ("bot.core.runtime.audit", "ModerationLogAuditSink"),
    "RestrictUserAction": ("bot.core.runtime.actions", "RestrictUserAction"),
    "RuntimeAuditService": ("bot.core.runtime.audit", "RuntimeAuditService"),
    "RuntimeEvent": ("bot.core.runtime.events", "RuntimeEvent"),
    "RuntimeEventType": ("bot.core.runtime.events", "RuntimeEventType"),
    "ScheduledAnnouncementRequest": ("bot.core.runtime.automation", "ScheduledAnnouncementRequest"),
    "SendNoticeAction": ("bot.core.runtime.actions", "SendNoticeAction"),
    "SendRuntimeMessageAction": ("bot.core.runtime.actions", "SendRuntimeMessageAction"),
    "schedule_delay_seconds": ("bot.core.runtime.admin", "schedule_delay_seconds"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
