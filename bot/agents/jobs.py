from __future__ import annotations

from typing import Any

GROUP_MEMBER_BROADCAST_JOB_TYPE = "group_member_broadcast"
ADD_CONTACT_JOB_TYPE = "add_contact"
SCRAPER_GROUP_INFO_JOB_TYPE = "scraper_group_info"
SCRAPER_MEMBERS_JOB_TYPE = "scraper_members"
SCRAPER_MESSAGES_JOB_TYPE = "scraper_messages"
SCRAPER_FULL_GROUP_JOB_TYPE = "scraper_full_group"


def _normalize_group_reference(value: Any) -> int | str:
    if isinstance(value, int):
        return value
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("source_group_id is required")
    if raw.lstrip("-").isdigit():
        return int(raw)
    return raw


def normalize_group_member_broadcast_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    normalized = dict(payload or {})
    message = str(normalized.get("message") or "").strip()
    if not message:
        raise ValueError("message is required")
    source_group_title = str(normalized.get("source_group_title") or "").strip()

    try:
        threshold = int(normalized.get("threshold"))
    except (TypeError, ValueError) as exc:
        raise ValueError("threshold must be a positive integer") from exc
    if threshold <= 0:
        raise ValueError("threshold must be a positive integer")

    interval_raw = normalized.get("interval_seconds", 0)
    try:
        interval_seconds = float(interval_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("interval_seconds must be a non-negative number") from exc
    if interval_seconds < 0:
        raise ValueError("interval_seconds must be a non-negative number")

    selected_user_ids: list[int] = []
    for value in list(normalized.get("selected_user_ids") or []):
        try:
            user_id = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("selected_user_ids must contain valid integer user ids") from exc
        if user_id <= 0:
            raise ValueError("selected_user_ids must contain valid integer user ids")
        if user_id not in selected_user_ids:
            selected_user_ids.append(user_id)

    return {
        "source_group_id": _normalize_group_reference(normalized.get("source_group_id")),
        "source_group_title": source_group_title,
        "message": message,
        "threshold": threshold,
        "interval_seconds": interval_seconds,
        "skip_bots": bool(normalized.get("skip_bots", True)),
        "selected_user_ids": selected_user_ids,
    }
