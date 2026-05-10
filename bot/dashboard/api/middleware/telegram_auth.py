from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl, unquote

from fastapi import HTTPException

from bot.config import get_settings


def verify_telegram_init_data(init_data: str) -> dict[str, str]:
    parsed = dict(parse_qsl(unquote(init_data), keep_blank_values=True))
    received_hash = parsed.pop('hash', None)
    if not received_hash:
      raise HTTPException(status_code=401, detail='Missing hash')

    check_string = '\n'.join(f'{key}={value}' for key, value in sorted(parsed.items()))
    bot_token = get_settings().bot_token
    secret = hmac.new(b'WebAppData', bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        raise HTTPException(status_code=401, detail='Invalid initData')
    if time.time() - int(parsed.get('auth_date', 0)) > 86400:
        raise HTTPException(status_code=401, detail='initData expired')

    # Validate that `user` remains JSON-decodable when present.
    user_data = parsed.get('user')
    if user_data:
        try:
            json.loads(user_data)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=401, detail='Invalid user payload') from exc

    return parsed
