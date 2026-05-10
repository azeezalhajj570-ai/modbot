from __future__ import annotations

from bot.automation.models import TaskDefinition
from bot.automation.task_modules import build_builtin_task_definitions


class Registry:
    def __init__(self) -> None:
        self._definitions: dict[str, TaskDefinition] = {}

    def register(self, definition: TaskDefinition) -> None:
        self._definitions[definition.key] = definition

    def get(self, key: str) -> TaskDefinition:
        try:
            return self._definitions[key]
        except KeyError as exc:
            raise KeyError(f"Unknown task: {key}") from exc

    def list(self) -> list[TaskDefinition]:
        return list(self._definitions.values())

def build_default_registry() -> Registry:
    registry = Registry()
    for definition in build_builtin_task_definitions():
        registry.register(definition)
    return registry
