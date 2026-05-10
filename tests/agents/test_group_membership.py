from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from telethon.errors import FloodWaitError, RPCError, UserAlreadyParticipantError, UserPrivacyRestrictedError
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.tl.functions.messages import AddChatUserRequest
from telethon.tl.types import Channel, Chat, ChatPhotoEmpty, User

from bot.agents.group_membership import (
    ERROR_FLOOD_WAIT,
    ERROR_PEER_NOT_FOUND,
    ERROR_UNKNOWN,
    ERROR_USER_ALREADY_IN_GROUP,
    ERROR_USER_PRIVACY_RESTRICTED,
    add_user_to_group,
)


def _build_user(user_id: int) -> User:
    return User(
        id=user_id,
        is_self=False,
        contact=False,
        mutual_contact=False,
        deleted=False,
        bot=False,
        bot_chat_history=False,
        bot_nochats=False,
        verified=False,
        restricted=False,
        min=False,
        bot_inline_geo=False,
        support=False,
        scam=False,
        apply_min_photo=False,
        fake=False,
        bot_attach_menu=False,
        premium=False,
        attach_menu_enabled=False,
        bot_can_edit=False,
        close_friend=False,
        stories_hidden=False,
        stories_unavailable=False,
        contact_require_premium=False,
        bot_business=False,
        bot_has_main_app=False,
        access_hash=1,
        first_name="Target",
    )


def _build_channel(channel_id: int) -> Channel:
    return Channel(
        id=channel_id,
        title="Supergroup",
        photo=ChatPhotoEmpty(),
        date=datetime.now(UTC),
        megagroup=True,
    )


def _build_legacy_chat(chat_id: int) -> Chat:
    return Chat(
        id=chat_id,
        title="Legacy Group",
        photo=ChatPhotoEmpty(),
        participants_count=1,
        date=datetime.now(UTC),
        version=1,
    )


@pytest.mark.asyncio
async def test_add_user_to_group_succeeds_for_supergroup() -> None:
    client = AsyncMock()
    client.get_entity = AsyncMock(side_effect=[_build_user(77), _build_channel(1001)])
    client.return_value = None

    result = await add_user_to_group(client, -1001001, 77)

    assert result.success is True
    request = client.await_args.args[0]
    assert isinstance(request, InviteToChannelRequest)


@pytest.mark.asyncio
async def test_add_user_to_group_succeeds_for_legacy_group() -> None:
    client = AsyncMock()
    client.get_entity = AsyncMock(side_effect=[_build_user(78), _build_legacy_chat(222)])
    client.return_value = None

    result = await add_user_to_group(client, -222, 78)

    assert result.success is True
    request = client.await_args.args[0]
    assert isinstance(request, AddChatUserRequest)


@pytest.mark.asyncio
async def test_add_user_to_group_returns_already_in_group() -> None:
    client = AsyncMock()
    client.get_entity = AsyncMock(side_effect=[_build_user(79), _build_channel(1002)])
    client.side_effect = UserAlreadyParticipantError(request=None)

    result = await add_user_to_group(client, -1001002, 79)

    assert result.success is False
    assert result.error_code == ERROR_USER_ALREADY_IN_GROUP


@pytest.mark.asyncio
async def test_add_user_to_group_returns_privacy_restricted() -> None:
    client = AsyncMock()
    client.get_entity = AsyncMock(side_effect=[_build_user(80), _build_channel(1003)])
    client.side_effect = UserPrivacyRestrictedError(request=None)

    result = await add_user_to_group(client, -1001003, 80)

    assert result.success is False
    assert result.error_code == ERROR_USER_PRIVACY_RESTRICTED


@pytest.mark.asyncio
async def test_add_user_to_group_returns_flood_wait() -> None:
    client = AsyncMock()
    client.get_entity = AsyncMock(side_effect=[_build_user(81), _build_channel(1004)])
    client.side_effect = FloodWaitError(request=None, capture=42)

    result = await add_user_to_group(client, -1001004, 81)

    assert result.success is False
    assert result.error_code == ERROR_FLOOD_WAIT
    assert result.flood_wait_seconds == 42


@pytest.mark.asyncio
async def test_add_user_to_group_returns_peer_not_found() -> None:
    client = AsyncMock()
    client.get_entity = AsyncMock(side_effect=ValueError("unknown peer"))

    result = await add_user_to_group(client, -1001005, 82)

    assert result.success is False
    assert result.error_code == ERROR_PEER_NOT_FOUND


@pytest.mark.asyncio
async def test_add_user_to_group_returns_unknown_on_generic_telegram_error() -> None:
    client = AsyncMock()
    client.get_entity = AsyncMock(side_effect=[_build_user(83), _build_channel(1006)])
    client.side_effect = RPCError(request=None, message="boom")

    result = await add_user_to_group(client, -1001006, 83)

    assert result.success is False
    assert result.error_code == ERROR_UNKNOWN
