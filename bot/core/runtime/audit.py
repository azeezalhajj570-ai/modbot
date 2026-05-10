from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from bot.db.models import ModerationLog

COMPAT_AUDIT_SCHEMA_VERSION = 1
RUNTIME_AUDIT_META_KEYS = {
    "domain",
    "runtime_event",
    "runtime_action",
    "source_runtime",
    "correlation_id",
    "subject_type",
    "subject_id",
    "compat_schema_version",
    "selected_actions",
    "guard_outcomes",
    "execution_result",
}


@dataclass
class AuditEntry:
    action: str
    group_id: int
    actor_user_id: int | None
    target_user_id: int | None
    domain: str = "moderation"
    event_type: str | None = None
    action_type: str | None = None
    subject_type: str | None = None
    subject_id: str | None = None
    source_runtime: str = "runtime"
    correlation_id: str | None = None
    reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_details(self) -> dict[str, Any]:
        payload = dict(self.details)
        payload.update(
            {
                "domain": self.domain,
                "runtime_event": self.event_type,
                "runtime_action": self.action_type or self.action,
                "source_runtime": self.source_runtime,
                "correlation_id": self.correlation_id,
                "subject_type": self.subject_type,
                "subject_id": self.subject_id,
                "compat_schema_version": COMPAT_AUDIT_SCHEMA_VERSION,
            }
        )
        return {key: value for key, value in payload.items() if value is not None}


@dataclass
class RuntimeAuditCompatibility:
    action: str
    domain: str | None
    runtime_event: str | None
    runtime_action: str | None
    source_runtime: str | None
    correlation_id: str | None
    subject_type: str | None
    subject_id: str | None
    compat_schema_version: int | None
    selected_actions: list[str] = field(default_factory=list)
    guard_outcomes: list[dict[str, Any]] = field(default_factory=list)
    execution_result: dict[str, Any] = field(default_factory=dict)
    detail_payload: dict[str, Any] = field(default_factory=dict)

    @property
    def is_runtime_audit(self) -> bool:
        return bool(self.runtime_event)


def parse_runtime_audit_compatibility(log: ModerationLog) -> RuntimeAuditCompatibility:
    details = dict(log.details or {})
    execution_result = dict(details.get("execution_result") or {})
    if not execution_result:
        execution_result = {
            key: value
            for key, value in details.items()
            if key not in RUNTIME_AUDIT_META_KEYS
        }
    selected_actions = list(details.get("selected_actions") or [])
    if not selected_actions and details.get("runtime_action"):
        selected_actions = [str(details["runtime_action"])]
    compat_schema_version = details.get("compat_schema_version")
    try:
        compat_schema_version = int(compat_schema_version) if compat_schema_version is not None else None
    except (TypeError, ValueError):
        compat_schema_version = None
    return RuntimeAuditCompatibility(
        action=log.action,
        domain=details.get("domain"),
        runtime_event=details.get("runtime_event"),
        runtime_action=details.get("runtime_action"),
        source_runtime=details.get("source_runtime"),
        correlation_id=details.get("correlation_id"),
        subject_type=details.get("subject_type"),
        subject_id=details.get("subject_id"),
        compat_schema_version=compat_schema_version,
        selected_actions=selected_actions,
        guard_outcomes=list(details.get("guard_outcomes") or []),
        execution_result=execution_result,
        detail_payload=details,
    )


def serialize_guard_result(result: Any) -> dict[str, Any]:
    return {
        "decision": getattr(result, "decision", None),
        "code": getattr(result, "code", None),
        "reason": getattr(result, "reason", None),
        "details": dict(getattr(result, "details", None) or {}),
    }


class AuditSink(Protocol):
    async def write(self, entry: AuditEntry) -> None:
        ...


@dataclass
class ModerationLogAuditSink:
    session: Any

    async def write(self, entry: AuditEntry) -> None:
        self.session.add(
            ModerationLog(
                group_id=entry.group_id,
                action=entry.action,
                target_user_id=entry.target_user_id,
                admin_user_id=entry.actor_user_id,
                reason=entry.reason,
                details=entry.to_details(),
            )
        )


@dataclass
class RuntimeAuditService:
    sink: AuditSink

    async def record(self, entry: AuditEntry) -> None:
        await self.sink.write(entry)
