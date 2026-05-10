from __future__ import annotations

import structlog
from typing import Any
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.automation.models import ActionTemplate, TaskDefinition, TaskEvent, TaskTrigger

logger = structlog.get_logger(__name__)


def _render_template(template: str, event: TaskEvent) -> str:
    text = str(event.payload.get("text") or "")
    return template.format(
        text=text,
        user_id=event.user_id or "",
        group_id=event.group_id,
        group_title=str(event.payload.get("group_title") or ""),
        message_id=event.payload.get("message_id") or "",
        first_name=str(event.payload.get("first_name") or ""),
        full_name=str(event.payload.get("full_name") or ""),
        username=str(event.payload.get("username") or ""),
    )


def _normalize_destination(value: Any) -> int | str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("destination is required")
    if raw.lstrip("-").isdigit():
        return int(raw)
    return raw


def _normalize_notify_delivery_mode(value: Any) -> str:
    mode = str(value or "text").strip().lower()
    valid_modes = {"text", "forward", "copy", "text_and_forward", "text_and_copy", "approval_request"}
    if mode not in valid_modes:
        raise ValueError("delivery_mode is invalid")
    return mode


def _normalize_inline_buttons(value: Any) -> list[dict[str, str]]:
    if value in (None, "", []):
        return []
    if not isinstance(value, list):
        raise ValueError("inline_buttons must be a list")
    normalized: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("inline_buttons entries must be objects")
        text = str(item.get("text") or "").strip()
        url = str(item.get("url") or "").strip()
        if not text and not url:
            continue
        if not text or not url:
            raise ValueError("inline_buttons entries require text and url")
        normalized.append({"text": text, "url": url})
    return normalized


def _build_inline_keyboard(config: dict[str, Any]) -> InlineKeyboardMarkup | None:
    rows = [
        [InlineKeyboardButton(text=item["text"], url=item["url"])]
        for item in _normalize_inline_buttons(config.get("inline_buttons"))
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


async def reply_message_handler(config: dict[str, Any], event: TaskEvent) -> dict[str, Any]:
    template = str(config.get("message_template") or "").strip()
    if not template:
        raise ValueError("message_template is required")

    reply_mode = str(config.get("reply_mode") or "public").strip().lower()
    result = {
        "text": _render_template(template, event),
    }
    reply_markup_type = str(config.get("reply_markup_type") or "none").strip().lower()
    if reply_markup_type not in {"none", "inline_buttons"}:
        raise ValueError("reply_markup_type is invalid")
    inline_buttons = _normalize_inline_buttons(config.get("inline_buttons"))
    if reply_markup_type == "inline_buttons" or inline_buttons:
        if not inline_buttons:
            raise ValueError("inline_buttons are required when reply_markup_type is inline_buttons")
        result["inline_buttons"] = inline_buttons
    else:
        reply_markup = _build_inline_keyboard(config)
        if reply_markup is not None:
            result["reply_markup"] = reply_markup
    if reply_mode == "private" and event.user_id is not None:
        result["chat_id"] = event.user_id
    else:
        result["reply_to_message_id"] = event.payload.get("message_id")
    delete_after_seconds = int(config.get("delete_after_seconds") or 0)
    if delete_after_seconds > 0:
        result["delete_after_seconds"] = delete_after_seconds
    return result


async def welcome_flow_handler(config: dict[str, Any], event: TaskEvent) -> dict[str, Any]:
    template = str(config.get("message_template") or "").strip()
    if not template:
        raise ValueError("message_template is required")

    text = _render_template(template, event)
    result = {
        "text": text,
        "reply_to_message_id": event.payload.get("message_id"),
        "metadata": {"capture_type": "welcome_flow"},
    }
    scheduled_follow_up_message = str(config.get("scheduled_follow_up_message") or "").strip()
    delay_seconds = int(config.get("follow_up_delay_seconds") or 0)
    if scheduled_follow_up_message and delay_seconds > 0:
        result["follow_up"] = {
            "text": _render_template(scheduled_follow_up_message, event),
            "delay_seconds": delay_seconds,
        }
        follow_up_delete_after_seconds = int(config.get("follow_up_delete_after_seconds") or 0)
        if follow_up_delete_after_seconds > 0:
            result["follow_up"]["delete_after_seconds"] = follow_up_delete_after_seconds
    delete_after_seconds = int(config.get("delete_after_seconds") or 0)
    if delete_after_seconds > 0:
        result["delete_after_seconds"] = delete_after_seconds
    return result


async def lead_capture_handler(config: dict[str, Any], event: TaskEvent) -> dict[str, Any]:
    template = str(config.get("ack_template") or "").strip()
    if not template:
        raise ValueError("ack_template is required")

    text = _render_template(template, event)
    if bool(config.get("ask_contact")):
        text = f"{text}\n\nPlease share your preferred contact details."
    return {
        "text": text,
        "reply_to_message_id": event.payload.get("message_id"),
        "metadata": {
            "lead_label": str(config.get("lead_label") or "general"),
            "capture_type": "lead_capture",
            "message_text": str(event.payload.get("text") or ""),
        },
        **({"delete_after_seconds": int(config.get("delete_after_seconds") or 0)} if int(config.get("delete_after_seconds") or 0) > 0 else {}),
    }


async def escalation_alert_handler(config: dict[str, Any], event: TaskEvent) -> dict[str, Any]:
    template = str(config.get("message_template") or "").strip()
    if not template:
        raise ValueError("message_template is required")

    escalation_reason = str(config.get("escalation_reason") or "").strip()
    text = _render_template(template, event)
    if escalation_reason:
        text = f"{text}\n\nReason: {escalation_reason}"
    return {
        "text": text,
        "reply_to_message_id": event.payload.get("message_id"),
        "metadata": {"capture_type": "escalation_alert"},
        **({"delete_after_seconds": int(config.get("delete_after_seconds") or 0)} if int(config.get("delete_after_seconds") or 0) > 0 else {}),
    }


async def notify_destination_handler(config: dict[str, Any], event: TaskEvent) -> dict[str, Any]:
    template = str(config.get("message_template") or "").strip()
    destination = _normalize_destination(config.get("destination"))
    delivery_mode = _normalize_notify_delivery_mode(config.get("delivery_mode"))
    suggested_reply_template = str(config.get("suggested_reply_template") or "").strip()
    approval_requested = delivery_mode == "approval_request" or bool(suggested_reply_template)
    if approval_requested:
        if not suggested_reply_template:
            raise ValueError("suggested_reply_template is required for approval_request delivery mode")
        if event.user_id is None:
            raise ValueError("A sender user_id is required for approval-based destination notifications")
        sender_name = (
            str(event.payload.get("full_name") or "").strip()
            or str(event.payload.get("first_name") or "").strip()
            or str(event.payload.get("username") or "").strip()
            or str(event.user_id)
        )
        source_group_title = str(event.payload.get("group_title") or "").strip() or str(event.group_id)
        original_message = str(event.payload.get("text") or "").strip() or "[No message text]"
        private_reply_text = _render_template(suggested_reply_template, event)
        prompt_sections: list[str] = []
        if template:
            prompt_sections.append(_render_template(template, event))
        prompt_sections.extend(
            [
                f"Sender: {sender_name} ({event.user_id})",
                f"Group: {source_group_title}",
                "User message:",
                original_message,
                "Suggested private reply:",
                private_reply_text,
            ]
        )
        logger.info(
            "notify_destination_approval_request_built",
            group_id=event.group_id,
            user_id=event.user_id,
            destination=str(destination),
            source_chat_id=event.payload.get("chat_id", event.group_id),
            source_message_id=event.payload.get("message_id"),
            has_template=bool(template),
            prompt_length=len("\n\n".join(prompt_sections)),
            private_reply_length=len(private_reply_text),
        )
        return {
            "approval_request": {
                "chat_id": destination,
                "prompt_text": "\n\n".join(prompt_sections) + "\n\nApprove sending this private reply?",
                "private_reply_text": private_reply_text,
                "target_user_id": event.user_id,
                "source_group_title": source_group_title,
                "original_message_text": original_message,
                "source_chat_id": event.payload.get("chat_id", event.group_id),
                "source_message_id": event.payload.get("message_id"),
            },
            "metadata": {
                "capture_type": "notify_destination",
                "delivery_mode": "approval_request",
                "destination": str(destination),
                "message_text": str(event.payload.get("text") or ""),
                "source_chat_id": str(event.payload.get("chat_id", event.group_id)),
                "source_group_title": source_group_title,
                "source_message_id": str(event.payload.get("message_id") or ""),
                "source_user_id": str(event.user_id or ""),
            },
        }

    requires_text = delivery_mode in {"text", "text_and_forward", "text_and_copy"}
    if requires_text and not template:
        raise ValueError("message_template is required")

    source_chat_id = event.payload.get("chat_id", event.group_id)
    source_message_id = event.payload.get("message_id")
    source_group_title = str(event.payload.get("group_title") or "").strip()
    result = {
        "chat_id": destination,
        "metadata": {
            "capture_type": "notify_destination",
            "delivery_mode": delivery_mode,
            "destination": str(destination),
            "message_text": str(event.payload.get("text") or ""),
            "source_chat_id": str(source_chat_id),
            "source_group_title": source_group_title,
            "source_message_id": str(source_message_id or ""),
            "source_user_id": str(event.user_id or ""),
        },
    }
    if requires_text:
        rendered_text = _render_template(template, event)
        should_prefix_group_title = source_group_title and "{group_title}" not in template
        result["text"] = f"[{source_group_title}] {rendered_text}" if should_prefix_group_title else rendered_text
    if delivery_mode in {"forward", "text_and_forward"}:
        result["forward_from_chat_id"] = source_chat_id
        result["forward_message_id"] = source_message_id
    if delivery_mode in {"copy", "text_and_copy"}:
        result["copy_from_chat_id"] = source_chat_id
        result["copy_message_id"] = source_message_id
    delete_after_seconds = int(config.get("delete_after_seconds") or 0)
    if delete_after_seconds > 0:
        result["delete_after_seconds"] = delete_after_seconds
    logger.info(
        "notify_destination_delivery_built",
        group_id=event.group_id,
        user_id=event.user_id,
        destination=str(destination),
        delivery_mode=delivery_mode,
        source_chat_id=source_chat_id,
        source_message_id=source_message_id,
        has_text=bool(result.get("text")),
    )
    return result


def build_builtin_task_definitions() -> list[TaskDefinition]:
    return [
        TaskDefinition(
            key="reply_message",
            title="Reply To Group Message",
            description="Replies in a group when a message matches the configured conditions.",
            trigger="message.received",
            config_schema={
                "message_template": {
                    "type": "string",
                    "required": True,
                    "description": "Reply text. Supports {text}, {user_id}, {group_id}, {group_title}, {message_id}.",
                },
                "reply_mode": {
                    "type": "string",
                    "required": False,
                    "description": "Reply location: public (group) or private (direct message).",
                },
                "reply_markup_type": {
                    "type": "string",
                    "required": False,
                    "description": "Optional reply markup type. Supported value: inline_buttons.",
                },
                "inline_buttons": {
                    "type": "array",
                    "required": False,
                    "description": "Optional inline URL buttons in the form [{text, url}].",
                },
                "delete_after_seconds": {
                    "type": "integer",
                    "required": False,
                    "description": "Optional auto-delete delay for bot-sent replies.",
                },
            },
            handler=reply_message_handler,
            trigger_rule=TaskTrigger(event_name="message.received"),
            action_template=ActionTemplate(kind="send_runtime_message", metadata={"flow": "reply_message"}),
        ),
        TaskDefinition(
            key="welcome_flow",
            title="Welcome Flow Reply",
            description="Welcomes a newly joined member and can schedule a later follow-up.",
            trigger="member.joined",
            config_schema={
                "message_template": {
                    "type": "string",
                    "required": True,
                    "description": "Welcome message body.",
                },
                "scheduled_follow_up_message": {
                    "type": "string",
                    "required": False,
                    "description": "Optional delayed follow-up message.",
                },
                "follow_up_delay_seconds": {
                    "type": "integer",
                    "required": False,
                    "description": "Delay before sending the follow-up message.",
                },
            },
            handler=welcome_flow_handler,
            trigger_rule=TaskTrigger(event_name="member.joined"),
            action_template=ActionTemplate(kind="send_runtime_message", metadata={"flow": "welcome_flow"}),
        ),
        TaskDefinition(
            key="lead_capture",
            title="Lead Capture Reply",
            description="Acknowledges an inbound lead and asks for contact details if needed.",
            trigger="message.received",
            config_schema={
                "ack_template": {
                    "type": "string",
                    "required": True,
                    "description": "Lead acknowledgment text.",
                },
                "lead_label": {
                    "type": "string",
                    "required": False,
                    "description": "Optional lead label such as sales or support.",
                },
                "ask_contact": {
                    "type": "boolean",
                    "required": False,
                    "description": "Append a prompt asking for contact details.",
                },
            },
            handler=lead_capture_handler,
            trigger_rule=TaskTrigger(event_name="message.received"),
            action_template=ActionTemplate(kind="send_runtime_message", metadata={"flow": "lead_capture"}),
        ),
        TaskDefinition(
            key="escalation_alert",
            title="Escalation Alert Reply",
            description="Replies with an escalation notice for urgent or sensitive messages.",
            trigger="message.received",
            config_schema={
                "message_template": {
                    "type": "string",
                    "required": True,
                    "description": "Escalation response text.",
                },
                "escalation_reason": {
                    "type": "string",
                    "required": False,
                    "description": "Optional reason appended to the response.",
                },
            },
            handler=escalation_alert_handler,
            trigger_rule=TaskTrigger(event_name="message.received"),
            action_template=ActionTemplate(kind="send_runtime_message", metadata={"flow": "escalation_alert"}),
        ),
        TaskDefinition(
            key="notify_destination",
            title="Notify Destination",
            description="Sends a notification to a configured destination when a message matches the conditions.",
            trigger="message.received",
            config_schema={
                "message_template": {
                    "type": "string",
                    "required": True,
                    "description": "Notification text. Supports {text}, {user_id}, {group_id}, {group_title}, {message_id}, {first_name}, {full_name}, {username}.",
                },
                "destination": {
                    "type": "string",
                    "required": True,
                    "description": "Destination group/chat ID.",
                },
                "delivery_mode": {
                    "type": "string",
                    "required": False,
                    "description": "Delivery mode: text, forward, copy, text_and_forward, text_and_copy, or approval_request.",
                },
                "suggested_reply_template": {
                    "type": "string",
                    "required": False,
                    "description": "Used by approval_request mode. Builds the suggested private reply shown with inline approval buttons.",
                },
            },
            handler=notify_destination_handler,
            trigger_rule=TaskTrigger(event_name="message.received"),
            action_template=ActionTemplate(kind="send_runtime_message", metadata={"flow": "notify_destination"}),
        ),
    ]
