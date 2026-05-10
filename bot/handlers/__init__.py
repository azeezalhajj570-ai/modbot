from aiogram import Router

from bot.handlers.automation_notify import router as automation_notify_router
from bot.handlers.commands.dashboard import router as dashboard_router
from bot.handlers.commands.moderation import router as moderation_commands_router
from bot.handlers.commands.register_group import router as register_group_router
from bot.handlers.commands.start import router as start_router
from bot.handlers.commands.subscribe import router as subscribe_router
from bot.handlers.fallback import router as fallback_router
from bot.handlers.join_request import router as join_request_router
from bot.handlers.join_request_callbacks import router as join_request_callbacks_router
from bot.handlers.menu.reply_settings import router as reply_settings_router
from bot.handlers.menu.settings import router as settings_router
from bot.handlers.moderation.events import router as moderation_router


def build_router() -> Router:
    root = Router(name="root")
    root.include_router(automation_notify_router)
    root.include_router(start_router)
    root.include_router(dashboard_router)
    root.include_router(moderation_commands_router)
    root.include_router(register_group_router)
    root.include_router(subscribe_router)
    root.include_router(join_request_router)
    root.include_router(join_request_callbacks_router)
    root.include_router(reply_settings_router)
    root.include_router(settings_router)
    root.include_router(moderation_router)
    root.include_router(fallback_router)
    return root
