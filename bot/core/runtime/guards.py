from __future__ import annotations

from dataclasses import dataclass, field
from strenum import StrEnum
from typing import Any


class GuardDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


@dataclass
class GuardResult:
    decision: GuardDecision
    code: str | None = None
    reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class GuardPipeline:
    guards: list = field(default_factory=list)

    async def evaluate(self, event, action) -> GuardResult:
        for guard in self.guards:
            result = await guard.evaluate(event, action)
            if result.decision == GuardDecision.DENY:
                return result
        return GuardResult(decision=GuardDecision.ALLOW)
