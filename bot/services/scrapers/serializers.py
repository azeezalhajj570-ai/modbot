from __future__ import annotations

from datetime import datetime
from typing import Any


def build_scraped_member_row(
    *,
    scraped_group_id: int,
    tg_group_id: int,
    tg_user_id: int,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    full_name: str | None = None,
    phone: str | None = None,
    is_bot: bool = False,
    is_premium: bool = False,
    role: str | None = None,
    joined_date: datetime | None = None,
    raw_data: dict | None = None,
) -> dict[str, Any]:
    return {
        "scraped_group_id": scraped_group_id,
        "tg_group_id": tg_group_id,
        "tg_user_id": tg_user_id,
        "username": username,
        "first_name": first_name,
        "last_name": last_name,
        "full_name": full_name,
        "phone": phone,
        "is_bot": is_bot,
        "is_premium": is_premium,
        "role": role or "member",
        "joined_date": joined_date if isinstance(joined_date, datetime) else None,
        "raw_data": raw_data or {},
        "scraped_at": datetime.utcnow(),
    }


def build_scraped_message_row(
    *,
    scraped_group_id: int,
    tg_group_id: int,
    message_id: int,
    sender_user_id: int | None = None,
    sender_username: str | None = None,
    sender_first_name: str | None = None,
    sender_last_name: str | None = None,
    message_text: str | None = None,
    message_date: datetime | None = None,
    message_type: str = "text",
    media_file_id: str | None = None,
    media_url: str | None = None,
    reply_to_message_id: int | None = None,
    reply_to_top_id: int | None = None,
    forward_from_user_id: int | None = None,
    raw_data: dict | None = None,
) -> dict[str, Any]:
    return {
        "scraped_group_id": scraped_group_id,
        "tg_group_id": tg_group_id,
        "message_id": message_id,
        "sender_user_id": sender_user_id,
        "sender_username": sender_username,
        "sender_first_name": sender_first_name,
        "sender_last_name": sender_last_name,
        "message_text": message_text,
        "message_date": message_date,
        "message_type": message_type,
        "media_file_id": media_file_id,
        "media_url": media_url,
        "reply_to_message_id": reply_to_message_id,
        "reply_to_top_id": reply_to_top_id,
        "forward_from_user_id": forward_from_user_id,
        "raw_data": raw_data or {},
        "scraped_at": datetime.utcnow(),
    }


def serialize_participant_data(participant: Any) -> dict:
    raw_data = {}
    for attr in ["id", "access_hash", "username", "first_name", "last_name", "phone", "bot", "premium"]:
        value = getattr(participant, attr, None)
        if value is not None:
            raw_data[attr] = str(value) if not isinstance(value, (int, float, bool, str, type(None))) else value
    return raw_data


def serialize_message_data(message: Any) -> dict:
    from bot.services.scrapers.entity_resolver import extract_peer_id

    return {
        "id": getattr(message, "id", None),
        "date": str(getattr(message, "date", None)) if getattr(message, "date", None) else None,
        "text": getattr(message, "text", None) or getattr(message, "message", None),
        "sender_id": extract_peer_id(getattr(message, "sender_id", None)),
        "from_id": extract_peer_id(getattr(message, "from_id", None)),
    }


def build_member_row_from_participant(
    participant: Any,
    scraped_group_id: int,
    canonical_group_id: int,
    user_id: int,
) -> dict[str, Any]:
    first_name = str(getattr(participant, "first_name", None) or "").strip() or None
    last_name = str(getattr(participant, "last_name", None) or "").strip() or None
    full_name = " ".join(part for part in [first_name, last_name] if part).strip() or None

    role = "member"
    if hasattr(participant, "creator") and participant.creator:
        role = "creator"
    elif hasattr(participant, "admin_rights") and participant.admin_rights:
        role = "admin"
    elif hasattr(participant, "banned_rights") and participant.banned_rights:
        role = "restricted"

    joined_date = getattr(participant, "date", None)
    if isinstance(joined_date, int):
        joined_date = datetime.utcfromtimestamp(joined_date)

    return build_scraped_member_row(
        scraped_group_id=scraped_group_id,
        tg_group_id=canonical_group_id,
        tg_user_id=user_id,
        username=str(getattr(participant, "username", None) or "").strip() or None,
        first_name=first_name,
        last_name=last_name,
        full_name=full_name,
        phone=str(getattr(participant, "phone", None) or "").strip() or None,
        is_bot=bool(getattr(participant, "bot", False)),
        is_premium=bool(getattr(participant, "premium", False)),
        role=role,
        joined_date=joined_date if isinstance(joined_date, datetime) else None,
        raw_data=serialize_participant_data(participant),
    )


def build_member_row_from_sender(
    scraped_group_id: int,
    canonical_group_id: int,
    sender_user_id: int,
    sender_username: str | None,
    sender_first_name: str | None,
    sender_last_name: str | None,
    sender_raw_data: dict | None,
) -> dict[str, Any]:
    first_name = str(sender_first_name or "").strip() or None
    last_name = str(sender_last_name or "").strip() or None
    full_name = " ".join(part for part in [first_name, last_name] if part).strip() or None
    return build_scraped_member_row(
        scraped_group_id=scraped_group_id,
        tg_group_id=canonical_group_id,
        tg_user_id=int(sender_user_id),
        username=str(sender_username) if sender_username else None,
        first_name=first_name,
        last_name=last_name,
        full_name=full_name,
        role="member",
        raw_data=sender_raw_data,
    )


def build_message_row_from_msg(
    message: Any,
    scraped_group_id: int,
    canonical_group_id: int,
    message_id: int,
    sender_user_id: int | None,
    sender_username: str | None,
    sender_first_name: str | None,
    sender_last_name: str | None,
) -> dict[str, Any]:
    from bot.services.scrapers.entity_resolver import extract_peer_id

    message_text = getattr(message, "text", None) or getattr(message, "message", None)
    message_type = "text"
    media_file_id = None
    if hasattr(message, "media") and message.media:
        media = message.media
        if hasattr(media, "photo"):
            message_type = "photo"
            media_file_id = str(getattr(media.photo, "id", None)) if hasattr(media, "photo") else None
        elif hasattr(media, "document"):
            message_type = "document"
            media_file_id = str(getattr(media.document, "id", None)) if getattr(media, "document", None) else None
            if hasattr(media, "video"):
                message_type = "video"

    reply_to_message_id = None
    reply_to_top_id = None
    reply = getattr(message, "reply_to", None)
    if reply:
        reply_to_message_id = getattr(reply, "reply_to_msg_id", None)
        reply_to_top_id = getattr(reply, "reply_to_top_id", None)

    forward_from_user_id = None
    fwd_from = getattr(message, "fwd_from", None)
    if fwd_from:
        forward_from_user_id = extract_peer_id(getattr(fwd_from, "from_id", None))

    return build_scraped_message_row(
        scraped_group_id=scraped_group_id,
        tg_group_id=canonical_group_id,
        message_id=message_id,
        sender_user_id=int(sender_user_id) if sender_user_id is not None else None,
        sender_username=str(sender_username) if sender_username else None,
        sender_first_name=str(sender_first_name) if sender_first_name else None,
        sender_last_name=str(sender_last_name) if sender_last_name else None,
        message_text=str(message_text) if message_text else None,
        message_date=getattr(message, "date", None),
        message_type=message_type,
        media_file_id=media_file_id,
        media_url=None,
        reply_to_message_id=int(reply_to_message_id) if reply_to_message_id else None,
        reply_to_top_id=int(reply_to_top_id) if reply_to_top_id else None,
        forward_from_user_id=int(forward_from_user_id) if forward_from_user_id else None,
        raw_data=serialize_message_data(message),
    )
