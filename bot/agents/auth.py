"""Telegram login flow for agent accounts."""

from __future__ import annotations

from dataclasses import dataclass

from bot.agents.exceptions import AgentAuthError
from bot.config import get_settings
from bot.utils.encryption import encrypt_value


class AgentTelegramAuthError(AgentAuthError, ValueError):
    pass


class AgentTelegramTwoFactorRequired(AgentTelegramAuthError):
    def __init__(self, message: str, session_string: str | None = None) -> None:
        self.session_string = session_string
        super().__init__(message)


@dataclass
class AgentTelegramAuthSession:
    phone_number: str
    session_string: str
    phone_code_hash: str


@dataclass
class AgentTelegramAuthResult:
    telegram_user_id: int
    phone_number: str
    username: str | None
    full_name: str | None
    session_string: str


class AgentTelegramAuthService:
    async def start_login(self, *, phone_number: str) -> AgentTelegramAuthSession:
        client, session = self._build_client()
        try:
            await client.connect()
            result = await client.send_code_request(phone_number)
            return AgentTelegramAuthSession(
                phone_number=phone_number,
                session_string=session.save(),
                phone_code_hash=result.phone_code_hash,
            )
        except Exception as exc:
            raise AgentTelegramAuthError(str(exc)) from exc
        finally:
            await client.disconnect()

    async def verify_code(
        self,
        *,
        phone_number: str,
        code: str,
        phone_code_hash: str,
        session_string: str,
    ) -> AgentTelegramAuthResult:
        client, session = self._build_client(session_string=session_string)
        try:
            await client.connect()
            try:
                await client.sign_in(phone=phone_number, code=code, phone_code_hash=phone_code_hash)
            except self._session_password_error() as exc:
                updated_session = session.save()
                raise AgentTelegramTwoFactorRequired(
                    "Two-factor password required",
                    session_string=updated_session,
                ) from exc
            me = await client.get_me()
            return self._build_result(me=me, session=session)
        except AgentTelegramTwoFactorRequired:
            raise
        except Exception as exc:
            raise AgentTelegramAuthError(str(exc)) from exc
        finally:
            await client.disconnect()

    async def verify_password(
        self,
        *,
        password: str,
        session_string: str,
    ) -> AgentTelegramAuthResult:
        client, session = self._build_client(session_string=session_string)
        try:
            await client.connect()
            await client.sign_in(password=password)
            me = await client.get_me()
            return self._build_result(me=me, session=session)
        except Exception as exc:
            raise AgentTelegramAuthError(str(exc)) from exc
        finally:
            await client.disconnect()

    def _build_result(self, *, me, session) -> AgentTelegramAuthResult:
        full_name = " ".join(part for part in [getattr(me, "first_name", None), getattr(me, "last_name", None)] if part).strip()
        return AgentTelegramAuthResult(
            telegram_user_id=int(me.id),
            phone_number=str(getattr(me, "phone", "") or ""),
            username=getattr(me, "username", None),
            full_name=full_name or None,
            session_string=encrypt_value(session.save()),
        )

    def _build_client(self, *, session_string: str | None = None):
        settings = get_settings()
        if settings.telegram_api_id is None or not settings.telegram_api_hash:
            raise AgentTelegramAuthError("Telegram client auth is not configured")
        try:
            from telethon import TelegramClient
            from telethon.sessions import StringSession
        except ImportError as exc:
            raise AgentTelegramAuthError("Telethon dependency is not installed") from exc

        session = StringSession(session_string or "")
        client = TelegramClient(session, settings.telegram_api_id, settings.telegram_api_hash)
        return client, session

    def _session_password_error(self):
        try:
            from telethon.errors import SessionPasswordNeededError
        except ImportError as exc:
            raise AgentTelegramAuthError("Telethon dependency is not installed") from exc
        return SessionPasswordNeededError
