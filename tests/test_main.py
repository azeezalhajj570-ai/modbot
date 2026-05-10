from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.types import (
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeDefault,
    MenuButtonCommands,
)

from bot.main import _configure_bot_commands, _configure_chat_menu_button


@pytest.mark.asyncio
async def test_configure_chat_menu_button_sets_webapp_button() -> None:
    bot = SimpleNamespace(set_chat_menu_button=AsyncMock())
    settings = SimpleNamespace(webapp_url="https://example.com/webapp", dashboard_url=None)

    await _configure_chat_menu_button(bot, settings)

    menu_button = bot.set_chat_menu_button.await_args.kwargs["menu_button"]
    assert isinstance(menu_button, MenuButtonCommands)


@pytest.mark.asyncio
async def test_configure_chat_menu_button_falls_back_to_commands() -> None:
    bot = SimpleNamespace(set_chat_menu_button=AsyncMock())
    settings = SimpleNamespace(webapp_url=None, dashboard_url=None)

    await _configure_chat_menu_button(bot, settings)

    menu_button = bot.set_chat_menu_button.await_args.kwargs["menu_button"]
    assert isinstance(menu_button, MenuButtonCommands)


@pytest.mark.asyncio
async def test_configure_bot_commands_registers_expected_commands() -> None:
    bot = SimpleNamespace(set_my_commands=AsyncMock())

    await _configure_bot_commands(bot, "admin")

    assert bot.set_my_commands.await_count == 3

    default_call, private_call, admin_call = bot.set_my_commands.await_args_list

    assert default_call.args[0] == []
    assert isinstance(default_call.kwargs["scope"], BotCommandScopeDefault)

    assert [command.command for command in private_call.args[0]] == [
        "start",
        "dashboard",
        "scraper",
        "settings",
        "help",
        "lang",
        "subscribe",
    ]
    assert isinstance(private_call.kwargs["scope"], BotCommandScopeAllPrivateChats)

    assert [command.command for command in admin_call.args[0]] == [
        "dashboard",
        "settings",
        "help",
        "lang",
        "registergroup",
        "ban",
        "unban",
        "mute",
    ]
    assert isinstance(admin_call.kwargs["scope"], BotCommandScopeAllChatAdministrators)


@pytest.mark.asyncio
async def test_configure_bot_commands_registers_agents_commands() -> None:
    bot = SimpleNamespace(set_my_commands=AsyncMock())

    await _configure_bot_commands(bot, "agents")

    assert bot.set_my_commands.await_count == 3

    default_call, private_call, admin_call = bot.set_my_commands.await_args_list

    assert default_call.args[0] == []
    assert isinstance(default_call.kwargs["scope"], BotCommandScopeDefault)

    assert [command.command for command in private_call.args[0]] == [
        "start",
        "help",
        "lang",
    ]
    assert isinstance(private_call.kwargs["scope"], BotCommandScopeAllPrivateChats)

    assert admin_call.args[0] == []
    assert isinstance(admin_call.kwargs["scope"], BotCommandScopeAllChatAdministrators)
