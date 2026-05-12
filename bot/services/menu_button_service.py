from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import MenuButtonCommands, MenuButtonWebApp, WebAppInfo
from urllib.parse import urlsplit, urlunsplit

from bot.config import AppKind, get_settings


def _normalize_webapp_base_url(url: str) -> str:
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/")

    if path.endswith("/webapp/admin"):
        path = path[: -len("/admin")]
    elif path.endswith("/webapp/modbot"):
        path = path[: -len("/modbot")]
    elif path.endswith("/webapp/agents"):
        path = path[: -len("/agents")]
    elif path.endswith("/webapp/agents-app"):
        path = path[: -len("/agents-app")]

    return urlunsplit((parts.scheme, parts.netloc, path or "/", "", "")).rstrip("/")


def resolve_webapp_urls() -> dict[str, str] | None:
    admin_url = resolve_webapp_url("admin")
    agents_url = resolve_webapp_url("agents")
    configured_url = admin_url or agents_url
    if not configured_url:
        return None
    base_url = _normalize_webapp_base_url(configured_url)
    return {
        "base": base_url,
        "admin": admin_url or f"{base_url}/admin",
        "agents": agents_url or f"{base_url}/agents",
    }


def resolve_webapp_url(app_kind: AppKind | None = None) -> str | None:
    settings = get_settings()
    target_kind = app_kind or settings.bot_app_kind
    configured_url = settings.resolve_webapp_url(target_kind)
    if not configured_url:
        return None

    explicit_url = configured_url.strip().rstrip("/")
    normalized_path = urlsplit(explicit_url).path.rstrip("/")
    if normalized_path.endswith("/webapp/admin") or normalized_path.endswith("/webapp/modbot") or normalized_path.endswith("/webapp/agents"):
        return explicit_url
    if normalized_path.endswith("/webapp/agents-app"):
        return explicit_url[: -len("/agents-app")] + "/agents"
    base_url = _normalize_webapp_base_url(explicit_url)
    suffix = "admin" if target_kind == "admin" else "agents"
    return f"{base_url}/{suffix}"


logger = logging.getLogger(__name__)


async def configure_private_chat_menu_button(*, bot: Bot, user_id: int, enabled: bool, app_kind: AppKind | None = None) -> None:
    webapp_url = resolve_webapp_url(app_kind)
    if enabled and webapp_url:
        try:
            await bot.set_chat_menu_button(
                chat_id=user_id,
                menu_button=MenuButtonWebApp(
                    text="Open App",
                    web_app=WebAppInfo(url=webapp_url),
                ),
            )
            return
        except TelegramBadRequest:
            logger.warning("Failed to set webapp menu button (URL may be HTTP): %s", webapp_url)
    await bot.set_chat_menu_button(chat_id=user_id, menu_button=MenuButtonCommands())
