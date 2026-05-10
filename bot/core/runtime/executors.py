from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ActionExecutorRegistry:
    executors: dict[str, Any] = field(default_factory=dict)

    def register(self, kind: str, executor: Any) -> None:
        self.executors[kind] = executor

    async def execute(self, action: Any) -> dict[str, Any]:
        executor = self.executors.get(action.kind)
        if executor is None:
            raise KeyError(f"No executor registered for action kind {action.kind}")
        if hasattr(executor, "execute"):
            return await executor.execute(action)
        callback = executor
        return await callback(action)
