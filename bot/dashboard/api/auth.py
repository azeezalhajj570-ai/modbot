from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from fastapi import Header, HTTPException, Query, status

from bot.config import DashboardBrowserUser, get_settings
from bot.services.telegram_webapp_auth import TelegramWebAppAuthError, TelegramWebAppIdentity, validate_init_data
from bot.services.user_service import UserService


class DashboardJWTError(ValueError):
    pass


def _dashboard_jwt_secret() -> str:
    settings = get_settings()
    return settings.dashboard_jwt_secret or settings.bot_token


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode((value + padding).encode("ascii"))
    except Exception as exc:
        raise DashboardJWTError("Malformed JWT encoding") from exc


def _encode_jwt(payload: dict[str, Any], *, secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    encoded_header = _b64url_encode(json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    encoded_payload = _b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signature_input, hashlib.sha256).digest()
    return f"{encoded_header}.{encoded_payload}.{_b64url_encode(signature)}"


def create_dashboard_jwt(
    identity: TelegramWebAppIdentity,
    *,
    expires_in_seconds: int,
    now: int | None = None,
) -> str:
    issued_at = now if now is not None else int(time.time())
    payload = {
        "sub": str(identity.user_id),
        "username": identity.username,
        "first_name": identity.first_name,
        "last_name": identity.last_name,
        "iat": issued_at,
        "exp": issued_at + expires_in_seconds,
    }
    return _encode_jwt(payload, secret=_dashboard_jwt_secret())


def decode_dashboard_jwt(token: str, *, now: int | None = None) -> TelegramWebAppIdentity:
    try:
        encoded_header, encoded_payload, encoded_signature = token.split(".")
    except ValueError as exc:
        raise DashboardJWTError("Malformed JWT") from exc

    signature_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    expected_signature = hmac.new(
        _dashboard_jwt_secret().encode("utf-8"),
        signature_input,
        hashlib.sha256,
    ).digest()
    actual_signature = _b64url_decode(encoded_signature)
    if not hmac.compare_digest(expected_signature, actual_signature):
        raise DashboardJWTError("Invalid JWT signature")

    try:
        header = json.loads(_b64url_decode(encoded_header))
        payload = json.loads(_b64url_decode(encoded_payload))
    except json.JSONDecodeError as exc:
        raise DashboardJWTError("Malformed JWT payload") from exc

    if header.get("alg") != "HS256" or header.get("typ") != "JWT":
        raise DashboardJWTError("Unsupported JWT header")

    try:
        user_id = int(str(payload["sub"]))
        issued_at = int(payload["iat"])
        expires_at = int(payload["exp"])
    except (KeyError, TypeError, ValueError) as exc:
        raise DashboardJWTError("Invalid JWT claims") from exc

    current_ts = now if now is not None else int(time.time())
    if issued_at <= 0 or expires_at <= current_ts:
        raise DashboardJWTError("Expired JWT")

    return TelegramWebAppIdentity(
        user_id=user_id,
        username=payload.get("username"),
        first_name=payload.get("first_name"),
        last_name=payload.get("last_name"),
        auth_date=issued_at,
        raw={"auth_type": "jwt"},
    )


def verify_telegram_login(payload: dict[str, Any], *, bot_token: str, max_age_seconds: int) -> TelegramWebAppIdentity:
    data = {key: value for key, value in payload.items() if value is not None}
    incoming_hash = str(data.pop("hash", "") or "")
    if not incoming_hash:
        raise TelegramWebAppAuthError("Missing hash in Telegram login payload")

    try:
        auth_date = int(str(data.get("auth_date", "0")))
    except ValueError as exc:
        raise TelegramWebAppAuthError("Invalid auth_date in Telegram login payload") from exc

    current_ts = int(time.time())
    if auth_date <= 0 or current_ts - auth_date > max_age_seconds:
        raise TelegramWebAppAuthError("Expired Telegram login payload")

    secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
    expected_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, incoming_hash):
        raise TelegramWebAppAuthError("Invalid Telegram login signature")

    try:
        user_id = int(str(data["id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise TelegramWebAppAuthError("Invalid Telegram user id") from exc

    return TelegramWebAppIdentity(
        user_id=user_id,
        username=str(data.get("username") or "") or None,
        first_name=str(data.get("first_name") or "") or None,
        last_name=str(data.get("last_name") or "") or None,
        auth_date=auth_date,
        raw={key: str(value) for key, value in data.items()},
    )


def _validate_against_any_bot_token(validator, *, failure_message: str):
    settings = get_settings()
    last_error: Exception | None = None
    for token in settings.all_bot_tokens():
        try:
            return validator(token)
        except TelegramWebAppAuthError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise TelegramWebAppAuthError(failure_message)


def authenticate_browser_user(identifier: str, password: str) -> DashboardBrowserUser | None:
    normalized_identifier = identifier.strip().lower()
    if not normalized_identifier or not password:
        return None

    for user in get_settings().dashboard_browser_users:
        normalized_email = user.email.strip().lower()
        normalized_username = str(user.username or "").strip().lower()
        if normalized_identifier not in {normalized_email, normalized_username}:
            continue
        if hmac.compare_digest(user.password, password):
            return user
    return None


def browser_user_identity(user: DashboardBrowserUser) -> TelegramWebAppIdentity:
    return TelegramWebAppIdentity(
        user_id=user.user_id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        auth_date=int(time.time()),
        raw={"auth_type": "email"},
    )


async def issue_dashboard_token_for_browser_credentials(
    *,
    session,
    identifier: str,
    password: str,
) -> tuple[str, DashboardBrowserUser, TelegramWebAppIdentity]:
    matched_user = authenticate_browser_user(identifier, password)
    if matched_user is None:
        raise DashboardJWTError("Invalid email or password")

    settings = get_settings()
    identity = browser_user_identity(matched_user)
    full_name = " ".join(part for part in [identity.first_name, identity.last_name] if part).strip() or None
    user_service = UserService(session)
    await user_service.set_language(
        tg_user_id=identity.user_id,
        language_code=await user_service.resolve_language(identity.user_id, fallback=settings.default_language),
        username=identity.username or matched_user.email,
        full_name=full_name,
    )
    token = create_dashboard_jwt(identity, expires_in_seconds=settings.dashboard_jwt_exp_seconds)
    return token, matched_user, identity


async def issue_dashboard_token_for_telegram_login(
    *,
    session,
    payload: dict[str, Any],
) -> tuple[str, TelegramWebAppIdentity]:
    settings = get_settings()
    identity = _validate_against_any_bot_token(
        lambda token: verify_telegram_login(
            payload,
            bot_token=token,
            max_age_seconds=settings.telegram_webapp_auth_max_age_seconds,
        ),
        failure_message="No Telegram bot token configured for login verification",
    )
    full_name = " ".join(part for part in [identity.first_name, identity.last_name] if part).strip() or None
    user_service = UserService(session)
    await user_service.set_language(
        tg_user_id=identity.user_id,
        language_code=await user_service.resolve_language(identity.user_id, fallback=settings.default_language),
        username=identity.username,
        full_name=full_name,
    )
    token = create_dashboard_jwt(identity, expires_in_seconds=settings.dashboard_jwt_exp_seconds)
    return token, identity


def verify_telegram_init_data_identity(init_data: str) -> TelegramWebAppIdentity:
    settings = get_settings()
    return _validate_against_any_bot_token(
        lambda token: validate_init_data(
            init_data,
            bot_token=token,
            max_age_seconds=settings.telegram_webapp_auth_max_age_seconds,
        ),
        failure_message="No Telegram bot token configured for miniapp verification",
    )


def issue_dashboard_token_for_init_data(init_data: str) -> tuple[str, TelegramWebAppIdentity]:
    identity = verify_telegram_init_data_identity(init_data)
    token = create_dashboard_jwt(identity, expires_in_seconds=get_settings().dashboard_jwt_exp_seconds)
    return token, identity


async def extract_dashboard_identity(
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
    init_data: str | None = Query(default=None),
) -> TelegramWebAppIdentity:
    if authorization:
        token = authorization.strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        if not token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
        try:
            return decode_dashboard_jwt(token)
        except DashboardJWTError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    value = x_telegram_init_data or init_data
    if not value:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authentication")

    settings = get_settings()
    try:
        return verify_telegram_init_data_identity(value)
    except TelegramWebAppAuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
