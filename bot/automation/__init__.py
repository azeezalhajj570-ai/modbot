from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "ActionTemplate": ("bot.automation.models", "ActionTemplate"),
    "AgentJobExecutor": ("bot.automation.executors", "AgentJobExecutor"),
    "BaseTaskExecutor": ("bot.automation.executors", "BaseTaskExecutor"),
    "BotTaskExecutor": ("bot.automation.executors", "BotTaskExecutor"),
    "ConditionEvaluator": ("bot.automation.conditions", "ConditionEvaluator"),
    "Registry": ("bot.automation.registry", "Registry"),
    "RulesPlanner": ("bot.automation.planners", "RulesPlanner"),
    "TaskAssignment": ("bot.automation.models", "TaskAssignment"),
    "TaskCondition": ("bot.automation.models", "TaskCondition"),
    "TaskDefinition": ("bot.automation.models", "TaskDefinition"),
    "TaskEngine": ("bot.automation.engine", "TaskEngine"),
    "TaskEvent": ("bot.automation.models", "TaskEvent"),
    "TaskExecutionContext": ("bot.automation.models", "TaskExecutionContext"),
    "TaskExecutionResult": ("bot.automation.models", "TaskExecutionResult"),
    "TaskPlan": ("bot.automation.models", "TaskPlan"),
    "TaskTrigger": ("bot.automation.models", "TaskTrigger"),
    "build_default_registry": ("bot.automation.registry", "build_default_registry"),
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
