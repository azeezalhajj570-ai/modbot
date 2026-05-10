from __future__ import annotations

import pytest

from bot.core.event_bus import Event, EventBus


@pytest.mark.asyncio
async def test_event_bus_emits_to_all_subscribers() -> None:
    bus = EventBus()
    received: list[str] = []

    async def handler_a(event: Event) -> None:
        received.append(f"a:{event.payload['text']}")

    async def handler_b(event: Event) -> None:
        received.append(f"b:{event.payload['text']}")

    bus.subscribe("MessageReceived", handler_a)
    bus.subscribe("MessageReceived", handler_b)

    await bus.publish(Event(name="MessageReceived", group_id=1, user_id=2, payload={"text": "hello"}))

    assert "a:hello" in received
    assert "b:hello" in received


@pytest.mark.asyncio
async def test_event_bus_unsubscribe_stops_delivery() -> None:
    bus = EventBus()
    received: list[str] = []

    async def handler(event: Event) -> None:
        received.append(event.name)

    bus.subscribe("MessageReceived", handler)
    bus.unsubscribe("MessageReceived", handler)

    await bus.publish(Event(name="MessageReceived", group_id=1, user_id=2, payload={}))
    assert received == []


@pytest.mark.asyncio
async def test_event_bus_handler_error_isolated() -> None:
    bus = EventBus()
    called: list[str] = []

    async def bad(_event: Event) -> None:
        raise RuntimeError("boom")

    async def good(_event: Event) -> None:
        called.append("ok")

    bus.subscribe("MessageReceived", bad)
    bus.subscribe("MessageReceived", good)

    await bus.publish(Event(name="MessageReceived", group_id=1, user_id=2, payload={}))

    assert called == ["ok"]
