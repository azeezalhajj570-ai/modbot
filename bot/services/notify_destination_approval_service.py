from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
import structlog
from sqlalchemy import select

from bot.db.models import Agent, GroupSetting
from bot.services.settings_service import SettingsService

PENDING_NOTIFY_APPROVAL_PREFIX = "notify_destination_approval:"
logger = structlog.get_logger(__name__)


def _approval_setting_key(token: str) -> str:
    return f"{PENDING_NOTIFY_APPROVAL_PREFIX}{token}"


def build_notify_destination_approval_keyboard(*, group_id: int, token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Yes", callback_data=f"notify-destination:yes:{group_id}:{token}"),
                InlineKeyboardButton(text="Edit Reply", callback_data=f"notify-destination:edit:{group_id}:{token}"),
                InlineKeyboardButton(text="No", callback_data=f"notify-destination:no:{group_id}:{token}"),
            ]
        ]
    )


class NotifyDestinationApprovalService:
    def __init__(self, session) -> None:
        self.session = session
        self.settings = SettingsService(session)

    async def _resolve_agent_label(self, agent_id: int | None) -> str:
        if agent_id is None:
            return "Unknown agent"
        agent = (await self.session.execute(select(Agent).where(Agent.id == int(agent_id)))).scalar_one_or_none()
        if agent is None:
            return f"Agent #{int(agent_id)}"
        username = str((agent.details or {}).get("username") or "").strip().lstrip("@")
        if username:
            return f"@{username}"
        external = str(agent.external_account_id or "").strip().lstrip("@")
        if external:
            return f"@{external}"
        if agent.telegram_user_id is not None:
            return str(agent.telegram_user_id)
        return f"Agent #{agent.id}"

    async def create_prompt(
        self,
        *,
        group_id: int,
        assignment_id: str,
        task_key: str,
        agent_id: int | None,
        destination: int | str,
        prompt_text: str,
        private_reply_text: str,
        target_user_id: int,
        source_group_title: str | None = None,
        original_message_text: str | None = None,
        source_chat_id: int | str | None = None,
        source_message_id: int | None = None,
        bot,
    ) -> dict:
        token = uuid4().hex[:16]
        agent_label = await self._resolve_agent_label(agent_id)
        rendered_prompt_text = f"{prompt_text}\n\nAgent: {agent_label}"
        payload = {
            "token": token,
            "status": "pending",
            "assignment_id": assignment_id,
            "task_key": task_key,
            "agent_id": int(agent_id) if agent_id is not None else None,
            "agent_label": agent_label,
            "destination": str(destination),
            "prompt_text": rendered_prompt_text,
            "private_reply_text": private_reply_text,
            "target_user_id": int(target_user_id),
            "source_group_title": str(source_group_title or "").strip(),
            "original_message_text": str(original_message_text or "").strip(),
            "source_chat_id": str(source_chat_id) if source_chat_id is not None else "",
            "source_message_id": int(source_message_id) if source_message_id is not None else None,
            "created_at": datetime.utcnow().isoformat(),
        }
        logger.info(
            "notify_destination_prompt_store_pending",
            group_id=group_id,
            assignment_id=assignment_id,
            task_key=task_key,
            agent_id=agent_id,
            destination=str(destination),
            target_user_id=int(target_user_id),
            token=token,
        )
        await self.settings.set_value(group_id, _approval_setting_key(token), payload)
        logger.info(
            "notify_destination_prompt_sending",
            group_id=group_id,
            assignment_id=assignment_id,
            destination=str(destination),
            token=token,
        )
        message = await bot.send_message(
            chat_id=destination,
            text=rendered_prompt_text,
            reply_markup=build_notify_destination_approval_keyboard(group_id=group_id, token=token),
        )
        payload["prompt_message_id"] = getattr(message, "message_id", None)
        await self.settings.set_value(group_id, _approval_setting_key(token), payload)
        logger.info(
            "notify_destination_prompt_sent",
            group_id=group_id,
            assignment_id=assignment_id,
            destination=str(destination),
            target_user_id=int(target_user_id),
            token=token,
            prompt_message_id=payload["prompt_message_id"],
        )
        return payload

    async def get_prompt(self, *, group_id: int, token: str) -> dict | None:
        value = await self.settings.get_one(group_id, _approval_setting_key(token))
        return value if isinstance(value, dict) else None

    async def set_prompt(self, *, group_id: int, token: str, payload: dict) -> None:
        await self.settings.set_value(group_id, _approval_setting_key(token), payload)

    async def find_prompt_by_control_message(self, *, destination: int | str, prompt_message_id: int) -> tuple[int, dict] | None:
        rows = (
            await self.session.execute(
                select(GroupSetting.group_id, GroupSetting.value).where(GroupSetting.key.startswith(PENDING_NOTIFY_APPROVAL_PREFIX))
            )
        ).all()
        for row in rows:
            raw = row.value.get("value") if isinstance(row.value, dict) else None
            if not isinstance(raw, dict):
                continue
            if str(raw.get("destination") or "") != str(destination):
                continue
            if int(raw.get("prompt_message_id") or 0) != int(prompt_message_id):
                continue
            return int(row.group_id), raw
        return None

    async def mark_prompt(
        self,
        *,
        group_id: int,
        token: str,
        status: str,
        acted_by_user_id: int | None = None,
        acted_by_username: str | None = None,
        acted_by_name: str | None = None,
    ) -> dict | None:
        payload = await self.get_prompt(group_id=group_id, token=token)
        if payload is None:
            return None
        payload = dict(payload)
        payload["status"] = status
        payload["acted_at"] = datetime.utcnow().isoformat()
        if acted_by_user_id is not None:
            payload["acted_by_user_id"] = int(acted_by_user_id)
        if acted_by_username:
            payload["acted_by_username"] = acted_by_username
        if acted_by_name:
            payload["acted_by_name"] = acted_by_name
        await self.settings.set_value(group_id, _approval_setting_key(token), payload)
        logger.info(
            "notify_destination_prompt_marked",
            group_id=group_id,
            token=token,
            status=status,
            acted_by_user_id=acted_by_user_id,
            target_user_id=payload.get("target_user_id"),
        )
        return payload
