from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl


class TelegramWebAppAuthError(ValueError):
    pass


@dataclass
class TelegramWebAppIdentity:
    user_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    auth_date: int
    raw: dict[str, str]


def _build_data_check_string(values: dict[str, str]) -> str:
    return "\n".join(f"{key}={value}" for key, value in sorted(values.items(), key=lambda item: item[0]))


def validate_init_data(
    init_data: str,
    *,
    bot_token: str,
    max_age_seconds: int = 86_400,
    now: int | None = None,
) -> TelegramWebAppIdentity:
    if not init_data:
        raise TelegramWebAppAuthError("Missing Telegram init data")

    parsed = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    incoming_hash = parsed.pop("hash", None)
    if not incoming_hash:
        raise TelegramWebAppAuthError("Missing hash in init data")

    data_check_string = _build_data_check_string(parsed)
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, incoming_hash):
        raise TelegramWebAppAuthError("Invalid Telegram init data signature")

    try:
        auth_date = int(parsed.get("auth_date", "0"))
    except ValueError as exc:
        raise TelegramWebAppAuthError("Invalid auth_date in init data") from exc

    current_ts = now if now is not None else int(time.time())
    if auth_date <= 0 or current_ts - auth_date > max_age_seconds:
        raise TelegramWebAppAuthError("Expired Telegram init data")

    user_raw = parsed.get("user")
    if not user_raw:
        raise TelegramWebAppAuthError("Missing user payload in init data")

    try:
        user = json.loads(user_raw)
    except json.JSONDecodeError as exc:
        raise TelegramWebAppAuthError("Malformed Telegram user payload") from exc

    user_id = user.get("id")
    if not isinstance(user_id, int):
        raise TelegramWebAppAuthError("Invalid Telegram user id")

    return TelegramWebAppIdentity(
        user_id=user_id,
        username=user.get("username"),
        first_name=user.get("first_name"),
        last_name=user.get("last_name"),
        auth_date=auth_date,
        raw=parsed,
    )

