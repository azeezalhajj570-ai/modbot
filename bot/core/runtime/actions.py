from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModerationAction:
    kind: str
    group_id: int
    actor_user_id: int | None
    target_user_id: int
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AddWarningAction(ModerationAction):
    count: int = 1


@dataclass
class ClearWarningsAction(ModerationAction):
    pass


@dataclass
class RestrictUserAction(ModerationAction):
    pass


@dataclass
class BanUserAction(ModerationAction):
    pass


@dataclass
class SendRuntimeMessageAction:
    kind: str
    group_id: int
    chat_id: int | str
    text: str
    reply_to_message_id: int | None = None
    reply_markup: Any | None = None
    forward_from_chat_id: int | str | None = None
    forward_message_id: int | None = None
    copy_from_chat_id: int | str | None = None
    copy_message_id: int | None = None
    delete_after_seconds: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DeleteMessageAction:
    kind: str
    group_id: int
    chat_id: int
    message_id: int
    target_user_id: int | None
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SendNoticeAction:
    kind: str
    group_id: int
    chat_id: int
    notice_text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MaybeMuteUserAction:
    kind: str
    group_id: int
    chat_id: int
    target_user_id: int | None
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
