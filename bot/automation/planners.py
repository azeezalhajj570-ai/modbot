from __future__ import annotations

from bot.automation.conditions import ConditionEvaluator
from bot.automation.models import TaskAssignment, TaskDefinition, TaskEvent, TaskExecutionContext, TaskPlan


class RulesPlanner:
    def __init__(self, condition_evaluator: ConditionEvaluator | None = None) -> None:
        self.condition_evaluator = condition_evaluator or ConditionEvaluator()

    def plan(self, *, task: TaskDefinition, assignment: TaskAssignment, event: TaskEvent) -> TaskPlan | None:
        trigger = task.trigger_rule
        if trigger is None or trigger.event_name != event.name:
            return None

        conditions = assignment.condition_rules()
        if not self.condition_evaluator.matches_conditions(event, conditions):
            return None

        action_template = task.action_template
        if action_template is None:
            return None

        return TaskPlan(
            definition=task,
            assignment=assignment,
            action_template=action_template,
            context=TaskExecutionContext(event=event, trigger=trigger, conditions=conditions),
        )
