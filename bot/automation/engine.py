from __future__ import annotations

import logging

from bot.automation.conditions import ConditionEvaluator
from bot.automation.models import TaskAssignment, TaskEvent, TaskExecutionResult
from bot.automation.planners import RulesPlanner
from bot.automation.registry import Registry

logger = logging.getLogger(__name__)


class TaskEngine:
    def __init__(
        self,
        *,
        registry: Registry,
        condition_evaluator: ConditionEvaluator | None = None,
        planner: RulesPlanner | None = None,
        rate_limiter=None,
        rate_limit_per_group_minute: int | None = None,
    ) -> None:
        self.registry = registry
        evaluator = condition_evaluator or ConditionEvaluator()
        self.planner = planner or RulesPlanner(evaluator)
        self._rate_limiter = rate_limiter
        self._rate_limit_per_group_minute = rate_limit_per_group_minute or 0

    async def process(self, assignments: list[TaskAssignment], event: TaskEvent, executors: dict[str, object]) -> list[TaskExecutionResult]:
        group_id = event.group_id
        if self._rate_limiter is not None and self._rate_limit_per_group_minute > 0 and group_id:
            key = f"automation:group:{group_id}"
            allowed, _ = await self._rate_limiter.check_and_increment(
                key, self._rate_limit_per_group_minute, window_seconds=60
            )
            if not allowed:
                logger.info("Automation rate limit reached for group %s — skipping", group_id)
                return []

        results: list[TaskExecutionResult] = []
        for assignment in assignments:
            if not assignment.enabled:
                continue
            task = self.registry.get(assignment.task_key)
            plan = self.planner.plan(task=task, assignment=assignment, event=event)
            if plan is None:
                continue
            executor = executors.get(assignment.executor_type)
            if executor is None:
                continue
            output = await executor.execute(task, assignment, event)
            results.append(TaskExecutionResult(assignment=assignment, output=output, plan=plan))
        return results
