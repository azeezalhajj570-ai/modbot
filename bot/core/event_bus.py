from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import structlog

EventHandler = Callable[["Event"], Awaitable[None]]
logger = structlog.get_logger(__name__)


@dataclass
class Event:
    name: str
    group_id: int | None
    user_id: int | None
    payload: dict[str, Any]
    created_at: datetime = field(default_factory=datetime.utcnow)


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_name: str, handler: EventHandler) -> None:
        if handler not in self._subscribers[event_name]:
            self._subscribers[event_name].append(handler)

    def unsubscribe(self, event_name: str, handler: EventHandler) -> None:
        if handler in self._subscribers[event_name]:
            self._subscribers[event_name].remove(handler)

    async def publish(self, event: Event) -> None:
        handlers = list(self._subscribers.get(event.name, []))
        if not handlers:
            return
        results = await asyncio.gather(*(handler(event) for handler in handlers), return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logger.exception("event_handler_error", event_name=event.name, error=str(result))
