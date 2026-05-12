from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeDefault,
    MenuButtonCommands,
)
from redis.asyncio import Redis
import sentry_sdk

from bot.agents.listener import AgentListenerManager
from bot.config import AppKind, get_settings
from bot.core.event_bus import EventBus
from bot.core.menu_engine import MenuEngine
from bot.core.plugin_manager import PluginManager
from bot.db.bootstrap import ensure_schema
from bot.db.session import engine
from bot.handlers import build_router
from bot.middlewares.update_logging import UpdateLoggingMiddleware
from bot.utils.logging import configure_logging


async def _configure_chat_menu_button(bot: Bot, settings: SimpleNamespace) -> None:
    _ = settings
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())


async def _configure_bot_commands(bot: Bot, app_kind: AppKind = "admin") -> None:
    if app_kind == "agents":
        private_commands = [
            BotCommand(command="start", description="Open the agents menu"),
            BotCommand(command="help", description="Show help"),
            BotCommand(command="lang", description="Switch language"),
        ]
        admin_commands: list[BotCommand] = []
    else:
        private_commands = [
            BotCommand(command="start", description="Open the main menu"),
            BotCommand(command="menu", description="Open the main navigation menu"),
            BotCommand(command="help", description="Show help"),
            BotCommand(command="lang", description="Switch language"),
            BotCommand(command="subscribe", description="Request access"),
            BotCommand(command="stats", description="Group dashboard and analytics"),
            BotCommand(command="events", description="Review moderation events"),
            BotCommand(command="restricted", description="Manage restricted users"),
            BotCommand(command="task", description="Manage automation tasks"),
            BotCommand(command="schedule", description="Manage scheduled messages"),
            BotCommand(command="modsettings", description="Configure moderation settings"),
            BotCommand(command="warnings", description="Manage warning settings"),
            BotCommand(command="accessgate", description="Configure group access gate"),
            BotCommand(command="subscriptions", description="Manage subscriptions"),
        ]
        admin_commands = [
            BotCommand(command="help", description="Show help"),
            BotCommand(command="lang", description="Switch language"),
            BotCommand(command="menu", description="Open the main navigation menu"),
            BotCommand(command="registergroup", description="Register this group"),
            BotCommand(command="ban", description="Ban a replied user"),
            BotCommand(command="unban", description="Unban a replied user"),
            BotCommand(command="mute", description="Mute a replied user"),
            BotCommand(command="stats", description="Group dashboard and analytics"),
            BotCommand(command="restricted", description="Manage restricted users"),
            BotCommand(command="warnings", description="Manage warning settings"),
        ]

    await bot.set_my_commands(
        [],
        scope=BotCommandScopeDefault(),
    )
    await bot.set_my_commands(
        private_commands,
        scope=BotCommandScopeAllPrivateChats(),
    )
    await bot.set_my_commands(
        admin_commands,
        scope=BotCommandScopeAllChatAdministrators(),
    )


async def run_bot() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    logging.getLogger("aiogram").setLevel(getattr(logging, settings.aiogram_log_level.upper(), logging.WARNING))

    if settings.sentry_dsn:
        sentry_sdk.init(dsn=settings.sentry_dsn, traces_sample_rate=0.1)

    # Safety net for local/test environments only; production should rely on Alembic.
    if settings.run_schema_bootstrap:
        await ensure_schema(engine)

    bot = Bot(
        token=settings.resolve_bot_token(settings.bot_app_kind),
        session=AiohttpSession(timeout=settings.telegram_request_timeout),
    )
    # Ensure polling mode works even if this bot was previously configured for webhooks.
    await bot.delete_webhook(drop_pending_updates=False)
    await _configure_bot_commands(bot, settings.bot_app_kind)
    await _configure_chat_menu_button(bot, settings)
    redis = Redis.from_url(settings.redis_url)
    dispatcher = Dispatcher(storage=RedisStorage(redis=redis))
    if settings.log_raw_updates:
        dispatcher.update.outer_middleware(UpdateLoggingMiddleware())
    dispatcher.include_router(build_router())

    event_bus = EventBus()
    menu_engine = MenuEngine()
    plugin_manager = PluginManager()
    await plugin_manager.load_all(dispatcher, event_bus)
    agent_listener_manager: AgentListenerManager | None = None
    if settings.bot_app_kind == "admin":
        agent_listener_manager = AgentListenerManager(bot=bot)
        await agent_listener_manager.start()

    try:
        await dispatcher.start_polling(
            bot,
            polling_timeout=settings.telegram_polling_timeout,
            event_bus=event_bus,
            menu_engine=menu_engine,
            plugin_manager=plugin_manager,
            redis=redis,
        )
    finally:
        if agent_listener_manager is not None:
            await agent_listener_manager.stop()
        await dispatcher.storage.close()
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(run_bot())
