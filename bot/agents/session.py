"""Session lifecycle and health state manager for linked agent accounts."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import select

from bot.agents.exceptions import AgentBannedError, AgentFloodWaitError, AgentSessionError, AgentSessionRevokedError
from bot.config import get_settings
from bot.db.models import Agent
from bot.db.session import SessionLocal
from bot.utils.encryption import decrypt_value

if TYPE_CHECKING:
    from telethon import TelegramClient


logger = structlog.get_logger(__name__)

_client_pool: dict[int, "TelegramClient"] = {}
_client_locks: dict[int, asyncio.Lock] = {}
_client_lock_loops: dict[int, asyncio.AbstractEventLoop] = {}
_client_loops: dict[int, asyncio.AbstractEventLoop] = {}


def _get_client_lock(agent_id: int) -> asyncio.Lock:
    lock = _client_locks.get(agent_id)
    current_loop = asyncio.get_running_loop()
    
    # Check if lock was created on a different event loop
    if lock is not None:
        lock_loop = _client_lock_loops.get(agent_id)
        if lock_loop is not current_loop:
            # Lock was created on a different loop, recreate it
            lock = None
    
    if lock is None:
        lock = asyncio.Lock()
        _client_locks[agent_id] = lock
        _client_lock_loops[agent_id] = current_loop
    return lock


async def shutdown_client_pool() -> None:
    agent_ids = list(_client_pool.keys())
    for agent_id in agent_ids:
        lock = _get_client_lock(agent_id)
        async with lock:
            client = _client_pool.pop(agent_id, None)
            _client_loops.pop(agent_id, None)
            _client_locks.pop(agent_id, None)
            _client_lock_loops.pop(agent_id, None)
            if client is None:
                continue
            try:
                if client.is_connected():
                    await client.disconnect()
            except Exception:
                logger.exception("agent_session_pool_disconnect_failed", agent_id=agent_id)


class SessionManager:
    def __init__(self, *, redis_client: Any | None = None, session_factory=SessionLocal) -> None:
        self._redis = redis_client
        self._session_factory = session_factory

    def _state_key(self, agent_id: int) -> str:
        return f"agent:{agent_id}:state"

    def _retry_key(self, agent_id: int) -> str:
        return f"agent:{agent_id}:retry_after"

    async def _get_redis(self):
        if self._redis is not None:
            return self._redis
        try:
            from redis.asyncio import Redis
        except ImportError as exc:
            raise AgentSessionError("Redis async client is not installed") from exc
        self._redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
        return self._redis

    async def _set_state(self, agent_id: int, state: str, *, retry_after: int | None = None) -> None:
        client = await self._get_redis()
        bound_logger = logger.bind(agent_id=agent_id)
        if state == "flood_wait" and retry_after is not None:
            await client.set(self._state_key(agent_id), state, ex=retry_after)
            await client.set(self._retry_key(agent_id), str(retry_after), ex=retry_after)
        elif state == "banned":
            await client.set(self._state_key(agent_id), state)
            await client.set(self._retry_key(agent_id), "0")
        else:
            await client.set(self._state_key(agent_id), state)
        bound_logger.info("agent_session_state_changed", state=state, retry_after=retry_after)

    async def _get_state(self, agent_id: int) -> tuple[str, int | None]:
        client = await self._get_redis()
        raw_state = await client.get(self._state_key(agent_id))
        raw_retry_after = await client.get(self._retry_key(agent_id))
        retry_after = None
        if raw_retry_after not in {None, ""}:
            try:
                retry_after = int(raw_retry_after)
            except (TypeError, ValueError):
                retry_after = None
        return str(raw_state or "unknown"), retry_after

    async def _load_agent(self, agent_id: int) -> Agent:
        async with self._session_factory() as session:
            agent = (await session.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
        if agent is None or not agent.session_string or agent.auth_state != "active" or agent.status in {"banned", "failed"}:
            raise AgentSessionError("Agent session is unavailable")
        return agent

    async def _build_client(self, agent: Agent) -> "TelegramClient":
        settings = get_settings()
        if settings.telegram_api_id is None or not settings.telegram_api_hash:
            raise AgentSessionError("Telegram client auth is not configured")
        try:
            from telethon import TelegramClient
            from telethon.sessions import StringSession
        except ImportError as exc:
            raise AgentSessionError("Telethon dependency is not installed") from exc

        session_str = decrypt_value(agent.session_string)
        return TelegramClient(
            StringSession(session_str),
            settings.telegram_api_id,
            settings.telegram_api_hash,
        )

    async def _connect_client(self, agent_id: int, client: "TelegramClient") -> None:
        bound_logger = logger.bind(agent_id=agent_id)
        try:
            from telethon.errors import (
                AuthKeyDuplicatedError,
                AuthKeyNotFound,
                AuthKeyPermEmptyError,
                AuthKeyUnregisteredError,
                FloodWaitError,
                PhoneNumberBannedError,
                SessionExpiredError,
                SessionRevokedError,
                UnauthorizedError,
                UserDeactivatedBanError,
                UserDeactivatedError,
            )
        except ImportError as exc:
            raise AgentSessionError("Telethon dependency is not installed") from exc

        reconnect_attempted = False
        while True:
            try:
                await client.connect()
                break
            except ConnectionError as exc:
                if reconnect_attempted:
                    raise AgentSessionError(str(exc)) from exc
                reconnect_attempted = True
                try:
                    await client.disconnect()
                except Exception:
                    bound_logger.debug("agent_session_disconnect_before_reconnect_failed")
                continue
            except FloodWaitError as exc:
                await self.mark_flood_wait(agent_id, int(exc.seconds))
                raise AgentFloodWaitError(int(exc.seconds)) from exc
            except (PhoneNumberBannedError, UserDeactivatedBanError) as exc:
                await self.mark_banned(agent_id)
                raise AgentBannedError() from exc
            except (
                AuthKeyDuplicatedError,
                AuthKeyNotFound,
                AuthKeyPermEmptyError,
                AuthKeyUnregisteredError,
                SessionExpiredError,
                SessionRevokedError,
                UnauthorizedError,
                UserDeactivatedError,
            ) as exc:
                raise AgentSessionRevokedError("Agent session is no longer authorized") from exc
            except Exception as exc:
                bound_logger.exception("agent_session_connect_failed")
                raise AgentSessionError(str(exc)) from exc

    async def _get_or_create_client(self, agent_id: int, agent: Agent) -> "TelegramClient":
        client = _client_pool.get(agent_id)
        current_loop = asyncio.get_running_loop()
        
        # Check if client was created on a different event loop
        if client is not None:
            client_loop = _client_loops.get(agent_id)
            if client_loop is not current_loop:
                # Client was created on a different loop, disconnect and remove it
                try:
                    if client.is_connected():
                        await client.disconnect()
                except Exception:
                    pass
                _client_pool.pop(agent_id, None)
                _client_loops.pop(agent_id, None)
                client = None
        
        if client is None:
            client = await self._build_client(agent)
            _client_pool[agent_id] = client
            _client_loops[agent_id] = current_loop
        return client

    async def get_client(self, agent_id: int) -> "TelegramClient":
        state, retry_after = await self._get_state(agent_id)
        bound_logger = logger.bind(agent_id=agent_id)
        if state == "banned":
            bound_logger.warning("agent_session_unavailable", state=state)
            raise AgentBannedError()
        if state == "flood_wait":
            bound_logger.warning("agent_session_unavailable", state=state, retry_after=retry_after or 0)
            raise AgentFloodWaitError(retry_after or 0)

        agent = await self._load_agent(agent_id)
        lock = _get_client_lock(agent_id)
        async with lock:
            client = await self._get_or_create_client(agent_id, agent)
            if not client.is_connected():
                await self._connect_client(agent_id, client)

            try:
                is_authorized = await client.is_user_authorized()
            except ConnectionError:
                await self._connect_client(agent_id, client)
                is_authorized = await client.is_user_authorized()

            if not is_authorized:
                _client_pool.pop(agent_id, None)
                _client_loops.pop(agent_id, None)
                _client_locks.pop(agent_id, None)
                _client_lock_loops.pop(agent_id, None)
                await client.disconnect()
                raise AgentSessionRevokedError("Agent session is no longer authorized")

            await self._set_state(agent_id, "healthy")
            return client

    async def mark_flood_wait(self, agent_id: int, retry_after: int) -> None:
        await self._set_state(agent_id, "flood_wait", retry_after=max(retry_after, 0))

    async def mark_banned(self, agent_id: int) -> None:
        await self._set_state(agent_id, "banned")

    async def mark_failed(self, agent_id: int) -> None:
        async with self._session_factory() as session:
            agent = (await session.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
            if agent is None:
                return
            agent.status = "failed"
            agent.auth_state = "failed"
            agent.phone_code_hash = None
            await session.commit()

    async def is_available(self, agent_id: int) -> bool:
        state, _retry_after = await self._get_state(agent_id)
        if state in {"banned", "flood_wait"}:
            logger.bind(agent_id=agent_id).info("agent_session_availability_checked", available=False, state=state)
            return False
        try:
            await self._load_agent(agent_id)
        except AgentSessionError:
            logger.bind(agent_id=agent_id).info("agent_session_availability_checked", available=False, state="unknown")
            return False
        logger.bind(agent_id=agent_id).info("agent_session_availability_checked", available=True, state=state)
        return True
