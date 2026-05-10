from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


TaskHandler = Callable[[dict[str, Any], "TaskEvent"], Awaitable[dict[str, Any]]]


@dataclass
class TaskEvent:
    name: str
    group_id: int
    user_id: int | None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskTrigger:
    event_name: str


@dataclass
class TaskCondition:
    key: str
    value: Any
    operator: str = "equals"


@dataclass
class ActionTemplate:
    kind: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskDefinition:
    key: str
    title: str
    description: str
    trigger: str
    config_schema: dict[str, Any]
    handler: TaskHandler
    trigger_rule: TaskTrigger | None = None
    action_template: ActionTemplate | None = None
    planner_key: str = "rules"

    def __post_init__(self) -> None:
        if self.trigger_rule is None:
            self.trigger_rule = TaskTrigger(event_name=self.trigger)
        if self.action_template is None:
            self.action_template = ActionTemplate(kind=self.key)


@dataclass
class TaskAssignment:
    assignment_id: str
    task_key: str
    executor_type: str
    enabled: bool = True
    conditions: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    agent_id: int | None = None
    group_ids: list[int] = field(default_factory=list)
    group_tg_ids: list[int] = field(default_factory=list)
    group_titles: list[str] = field(default_factory=list)
    max_actions_per_hour: int | None = None
    min_delay_seconds: float | None = None

    def condition_rules(self) -> list[TaskCondition]:
        rules: list[TaskCondition] = []
        for key, value in self.conditions.items():
            operator = "equals"
            if key == "text_contains":
                operator = "contains"
            elif key == "text_contains_any":
                operator = "contains_any"
            rules.append(TaskCondition(key=key, value=value, operator=operator))
        return rules


@dataclass
class TaskExecutionContext:
    event: TaskEvent
    trigger: TaskTrigger
    conditions: list[TaskCondition] = field(default_factory=list)


@dataclass
class TaskPlan:
    definition: TaskDefinition
    assignment: TaskAssignment
    action_template: ActionTemplate
    context: TaskExecutionContext


@dataclass
class TaskExecutionResult:
    assignment: TaskAssignment
    output: dict[str, Any]
    plan: TaskPlan | None = None
