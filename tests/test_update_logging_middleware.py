from __future__ import annotations

from aiogram.types import Update
import pytest

from bot.middlewares.update_logging import UpdateLoggingMiddleware, logger


@pytest.mark.asyncio
async def test_update_logging_middleware_logs_raw_update(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[tuple[str, dict]] = []

    monkeypatch.setattr(
        logger,
        "info",
        lambda event_name, **kwargs: events.append((event_name, kwargs)),
    )

    middleware = UpdateLoggingMiddleware()
    update = Update.model_validate(
        {
            "update_id": 123,
            "message": {
                "message_id": 55,
                "date": 1_700_000_000,
                "chat": {"id": -100123, "type": "supergroup", "title": "Test"},
                "from": {"id": 42, "is_bot": False, "first_name": "Test"},
                "text": "hello",
            },
        }
    )

    handled = []

    async def handler(event, data):
        handled.append((event, data))
        return "ok"

    result = await middleware(handler, update, {"foo": "bar"})

    assert result == "ok"
    assert handled == [(update, {"foo": "bar"})]
    assert events == [
        (
            "telegram_update_received",
            {
                "update_id": 123,
                "event_type": "message",
                "payload": update.model_dump(exclude_none=True),
            },
        )
    ]
