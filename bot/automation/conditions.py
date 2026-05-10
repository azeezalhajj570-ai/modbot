from __future__ import annotations

from typing import Any

from bot.automation.models import TaskCondition, TaskEvent


class ConditionEvaluator:
    def _normalized_keywords(self, expected: Any) -> list[str]:
        if isinstance(expected, (list, tuple, set)):
            values = expected
        else:
            values = str(expected or "").replace("\n", ",").split(",")
        return [str(value).strip().lower() for value in values if str(value).strip()]

    def matches_conditions(self, event: TaskEvent, conditions: list[TaskCondition]) -> bool:
        if not conditions:
            return True
        return self.matches(event, {condition.key: condition.value for condition in conditions})

    def matches(self, event: TaskEvent, conditions: dict[str, Any]) -> bool:
        if not conditions:
            return True

        text = str(event.payload.get("text") or "")
        lowered_text = text.lower()
        for key, expected in conditions.items():
            if key == "text_contains":
                keywords = self._normalized_keywords(expected)
                if not keywords or not any(keyword in lowered_text for keyword in keywords):
                    return False
            elif key == "text_contains_any":
                keywords = self._normalized_keywords(expected)
                if not keywords or not any(keyword in lowered_text for keyword in keywords):
                    return False
            elif key == "contains_link":
                if bool(event.payload.get("contains_link")) is not bool(expected):
                    return False
            elif key == "chat_id":
                if int(event.payload.get("chat_id", event.group_id)) != int(expected):
                    return False
            elif key == "user_id":
                if event.user_id != int(expected):
                    return False
            elif key == "has_text":
                if bool(text) is not bool(expected):
                    return False
            elif event.payload.get(key) != expected:
                return False
        return True
