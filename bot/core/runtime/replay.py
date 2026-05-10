from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import desc, select

from bot.core.runtime.audit import parse_runtime_audit_compatibility
from bot.db.models import ModerationLog


@dataclass
class RuntimeReplayRecord:
    log_id: int
    group_id: int
    action: str
    domain: str | None
    runtime_event: str | None
    runtime_action: str | None
    source_runtime: str | None
    correlation_id: str | None
    subject_type: str | None
    subject_id: str | None
    selected_actions: list[str] = field(default_factory=list)
    guard_outcomes: list[dict[str, Any]] = field(default_factory=list)
    execution_result: dict[str, Any] = field(default_factory=dict)
    audit_result: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "log_id": self.log_id,
            "group_id": self.group_id,
            "action": self.action,
            "domain": self.domain,
            "runtime_event": self.runtime_event,
            "runtime_action": self.runtime_action,
            "source_runtime": self.source_runtime,
            "correlation_id": self.correlation_id,
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "selected_actions": self.selected_actions,
            "guard_outcomes": self.guard_outcomes,
            "execution_result": self.execution_result,
            "audit_result": self.audit_result,
        }


class RuntimeReplayService:
    def __init__(self, session) -> None:
        self.session = session

    async def get_record(self, *, log_id: int) -> RuntimeReplayRecord | None:
        row = (await self.session.execute(select(ModerationLog).where(ModerationLog.id == log_id))).scalar_one_or_none()
        if row is None:
            return None
        return self._to_record(row)

    async def list_records(self, *, group_id: int, limit: int = 50) -> list[RuntimeReplayRecord]:
        rows = (
            await self.session.execute(
                select(ModerationLog)
                .where(ModerationLog.group_id == group_id)
                .order_by(desc(ModerationLog.created_at), desc(ModerationLog.id))
                .limit(limit)
            )
        ).scalars()
        return [self._to_record(row) for row in rows if parse_runtime_audit_compatibility(row).is_runtime_audit]

    def _to_record(self, row: ModerationLog) -> RuntimeReplayRecord:
        audit = parse_runtime_audit_compatibility(row)
        return RuntimeReplayRecord(
            log_id=row.id,
            group_id=row.group_id,
            action=row.action,
            domain=audit.domain,
            runtime_event=audit.runtime_event,
            runtime_action=audit.runtime_action,
            source_runtime=audit.source_runtime,
            correlation_id=audit.correlation_id,
            subject_type=audit.subject_type,
            subject_id=audit.subject_id,
            selected_actions=audit.selected_actions,
            guard_outcomes=audit.guard_outcomes,
            execution_result=audit.execution_result,
            audit_result={
                "reason": row.reason,
                "target_user_id": row.target_user_id,
                "admin_user_id": row.admin_user_id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "compat_schema_version": audit.compat_schema_version,
            },
        )
