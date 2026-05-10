from __future__ import annotations

from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update
import structlog

logger = structlog.get_logger(__name__)


class UpdateLoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler,
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Update):
            logger.info(
                "telegram_update_received",
                update_id=event.update_id,
                event_type=event.event_type,
                payload=event.model_dump(exclude_none=True),
            )
        return await handler(event, data)
