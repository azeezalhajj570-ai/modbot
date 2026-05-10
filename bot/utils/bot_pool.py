from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from aiogram import Bot

from bot.config import get_settings


class BotPool:
    _instance: Bot | None = None

    @classmethod
    async def get(cls) -> Bot:
        if cls._instance is None:
            cls._instance = Bot(token=get_settings().bot_token)
        return cls._instance

    @classmethod
    async def close(cls) -> None:
        if cls._instance is not None:
            await cls._instance.session.close()
            cls._instance = None


@asynccontextmanager
async def bot_scope() -> AsyncIterator[Bot]:
    bot = await BotPool.get()
    try:
        yield bot
    finally:
        pass
