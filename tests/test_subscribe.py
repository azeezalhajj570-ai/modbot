from __future__ import annotations

import pytest

from bot.config import get_settings
from bot.handlers.commands.subscribe import request_subscription


@pytest.mark.asyncio
async def test_subscribe_notifies_bot_owners(
    patch_db_dependencies,
    session_factory,
    fake_message_factory,
    fake_bot,
    fsm_context_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOT_OWNER_IDS", "7001,7002")
    get_settings.cache_clear()
    monkeypatch.setattr("bot.handlers.commands.subscribe.SessionLocal", session_factory)

    message = fake_message_factory(
        chat_id=9001,
        chat_type="private",
        user_id=3333,
        text="/subscribe need access",
        bot=fake_bot,
        username="requester",
        full_name="Request User",
    )

    state = fsm_context_factory(user_id=3333, chat_id=9001)
    await request_subscription(message, state)

    assert len(message.log.answers) == 1
    assert message.log.answers[0]["text"] == "Thanks for your request. The owner will review it shortly."
    assert message.log.answers[0]["reply_markup"].remove_keyboard is True
    assert fake_bot.sent_messages == [
        (7001, "Subscription request #1\nFrom: requester (TG 3333)\nMessage: need access\nReview: https://app.test"),
        (7002, "Subscription request #1\nFrom: requester (TG 3333)\nMessage: need access\nReview: https://app.test"),
    ]
