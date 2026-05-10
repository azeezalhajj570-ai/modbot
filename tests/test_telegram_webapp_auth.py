from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

from bot.services.telegram_webapp_auth import TelegramWebAppAuthError, validate_init_data


def _build_init_data(
    *,
    bot_token: str,
    user_id: int = 1001,
    username: str = "tester",
    auth_date: int | None = None,
) -> str:
    payload = {
        "auth_date": str(auth_date or int(time.time())),
        "query_id": "AAEAAAE",
        "user": json.dumps({"id": user_id, "username": username, "first_name": "Test"}, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(payload.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    payload["hash"] = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    return urlencode(payload)


def test_validate_init_data_success() -> None:
    init_data = _build_init_data(bot_token="123456:TESTTOKEN")
    identity = validate_init_data(init_data, bot_token="123456:TESTTOKEN")
    assert identity.user_id == 1001
    assert identity.username == "tester"


def test_validate_init_data_rejects_tampered_hash() -> None:
    init_data = _build_init_data(bot_token="123456:TESTTOKEN") + "x"
    with pytest.raises(TelegramWebAppAuthError):
        validate_init_data(init_data, bot_token="123456:TESTTOKEN")


def test_validate_init_data_rejects_expired_payload() -> None:
    init_data = _build_init_data(bot_token="123456:TESTTOKEN", auth_date=int(time.time()) - 90_000)
    with pytest.raises(TelegramWebAppAuthError):
        validate_init_data(init_data, bot_token="123456:TESTTOKEN", max_age_seconds=60)

