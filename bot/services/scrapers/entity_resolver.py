from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Agent, ScrapedGroup
from bot.services.group_service import canonical_tg_group_id
from bot.services.scrapers.serializers import serialize_participant_data

logger = structlog.get_logger(__name__)


async def get_active_agent(agent_id: int, session: AsyncSession) -> Agent | None:
    stmt = select(Agent).where(
        Agent.id == agent_id,
        Agent.auth_state == "active",
        Agent.session_string.is_not(None),
        Agent.status != "banned",
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def resolve_group_entity(client: Any, tg_group_id: int, session: AsyncSession) -> Any:
    try:
        return await client.get_entity(tg_group_id)
    except ValueError:
        canonical_id = canonical_tg_group_id(tg_group_id)
        stmt = select(ScrapedGroup).where(ScrapedGroup.tg_group_id == canonical_id).limit(1)
        group_record = (await session.execute(stmt)).scalars().first()

        if group_record:
            if group_record.username:
                try:
                    return await client.get_entity(group_record.username)
                except Exception:
                    pass

            access_hash = group_record.raw_data.get("access_hash")
            if access_hash:
                from telethon.tl.types import InputPeerChannel, InputPeerChat

                if str(tg_group_id).startswith("-100"):
                    pure_id = int(str(tg_group_id)[4:])
                    try:
                        return await client.get_entity(InputPeerChannel(channel_id=pure_id, access_hash=int(access_hash)))
                    except Exception:
                        pass
                else:
                    try:
                        return await client.get_entity(InputPeerChat(chat_id=abs(tg_group_id)))
                    except Exception:
                        pass

        async for dialog in client.iter_dialogs():
            if int(dialog.id) == tg_group_id:
                return dialog.entity

        raise


async def get_or_create_group_from_client(
    *,
    client: Any,
    agent_id: int,
    tg_group_id: int,
    session: AsyncSession,
) -> ScrapedGroup:
    entity = await resolve_group_entity(client, int(tg_group_id), session)
    title = getattr(entity, "title", None)
    username = getattr(entity, "username", None)
    group_type = "channel" if getattr(entity, "broadcast", False) else "supergroup" if getattr(entity, "megagroup", False) else "group"
    member_count = getattr(entity, "participants_count", None) or getattr(entity, "user_count", None)
    description = getattr(entity, "about", None) if hasattr(entity, "about") else None

    raw_data = {
        "id": getattr(entity, "id", None),
        "access_hash": getattr(entity, "access_hash", None),
    }

    return await get_or_create_scraped_group(
        tg_group_id=int(tg_group_id),
        last_agent_id=agent_id,
        title=str(title) if title else None,
        username=str(username) if username else None,
        group_type=group_type,
        member_count=int(member_count) if member_count else None,
        description=str(description) if description else None,
        raw_data=raw_data,
        session=session,
    )


async def get_or_create_scraped_group(
    *,
    tg_group_id: int,
    last_agent_id: int | None = None,
    title: str | None = None,
    username: str | None = None,
    group_type: str = "group",
    member_count: int | None = None,
    description: str | None = None,
    raw_data: dict | None = None,
    commit: bool = True,
    session: AsyncSession,
) -> ScrapedGroup:
    from datetime import datetime

    canonical_id = canonical_tg_group_id(int(tg_group_id))
    group = (
        await session.execute(
            select(ScrapedGroup).where(ScrapedGroup.tg_group_id == canonical_id).limit(1)
        )
    ).scalars().first()

    now = datetime.utcnow()
    if group is None:
        group = ScrapedGroup(
            tg_group_id=canonical_id,
            last_agent_id=last_agent_id,
            title=title,
            username=username,
            group_type=group_type,
            member_count=member_count,
            description=description,
            raw_data=raw_data or {},
            created_at=now,
            updated_at=now,
        )
        session.add(group)
        if commit:
            await session.commit()
            await session.refresh(group)
        return group

    if last_agent_id is not None:
        group.last_agent_id = last_agent_id
    if title is not None:
        group.title = title
    if username is not None:
        group.username = username
    if group_type:
        group.group_type = group_type
    if member_count is not None:
        group.member_count = member_count
    if description is not None:
        group.description = description
    if raw_data:
        existing_raw = dict(group.raw_data or {})
        existing_raw.update(raw_data)
        group.raw_data = existing_raw

    group.updated_at = now
    if commit:
        await session.commit()
    return group


def is_missing_scraper_table_error(exc: Exception) -> bool:
    message = str(getattr(exc, "orig", exc)).lower()
    return "undefinedtableerror" in message or 'relation "scraped_' in message


def extract_peer_id(peer: Any) -> int | None:
    if peer is None:
        return None
    if isinstance(peer, int):
        return peer
    for attr in ("user_id", "channel_id", "chat_id", "id"):
        value = getattr(peer, attr, None)
        if isinstance(value, int):
            return value
    return None


async def extract_message_sender_data(
    message: Any,
) -> tuple[int | None, str | None, str | None, str | None, dict[str, Any]]:
    sender_user_id = extract_peer_id(getattr(message, "sender_id", None))
    sender_obj = getattr(message, "sender", None)
    if sender_obj is None:
        sender_user_id = sender_user_id or extract_peer_id(getattr(message, "from_id", None))
        try:
            if not sender_user_id:
                sender_obj = await message.get_sender()
            else:
                sender_obj = await message.get_sender()
        except Exception:
            sender_obj = None
    else:
        sender_user_id = sender_user_id or extract_peer_id(getattr(sender_obj, "id", None))

    sender_username = getattr(sender_obj, "username", None) if sender_obj else None
    sender_first_name = getattr(sender_obj, "first_name", None) if sender_obj else None
    sender_last_name = getattr(sender_obj, "last_name", None) if sender_obj else None

    if sender_obj:
        sender_raw_data = serialize_participant_data(sender_obj)
        sender_raw_data["source"] = "message_sender"
    else:
        sender_raw_data = {"source": "message_sender", "sender_id": sender_user_id}
        if sender_username:
            sender_raw_data["username"] = str(sender_username)
        if sender_first_name:
            sender_raw_data["first_name"] = str(sender_first_name)
        if sender_last_name:
            sender_raw_data["last_name"] = str(sender_last_name)

    return (
        sender_user_id,
        str(sender_username) if sender_username else None,
        str(sender_first_name) if sender_first_name else None,
        str(sender_last_name) if sender_last_name else None,
        sender_raw_data,
    )
