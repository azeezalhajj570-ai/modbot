from aiogram import Router

from bot.handlers.automation_notify import router as automation_notify_router
from bot.handlers.commands.dashboard import router as dashboard_router
from bot.handlers.commands.moderation import router as moderation_commands_router
from bot.handlers.commands.register_group import router as register_group_router
from bot.handlers.commands.start import router as start_router
from bot.handlers.commands.subscribe import router as subscribe_router
from bot.handlers.commands.new.menu import router as cmd_menu_router
from bot.handlers.commands.new.stats import router as cmd_stats_router
from bot.handlers.commands.new.events import router as cmd_events_router
from bot.handlers.commands.new.restricted import router as cmd_restricted_router
from bot.handlers.commands.new.warnings import router as cmd_warnings_router
from bot.handlers.commands.new.modsettings import router as cmd_modsettings_router
from bot.handlers.commands.new.accessgate import router as cmd_accessgate_router
from bot.handlers.commands.new.schedule import router as cmd_schedule_router
from bot.handlers.commands.new.task import router as cmd_task_router
from bot.handlers.commands.new.subscriptions import router as cmd_subscriptions_router
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
    root.include_router(cmd_menu_router)
    root.include_router(cmd_stats_router)
    root.include_router(cmd_events_router)
    root.include_router(cmd_restricted_router)
    root.include_router(cmd_warnings_router)
    root.include_router(cmd_modsettings_router)
    root.include_router(cmd_accessgate_router)
    root.include_router(cmd_schedule_router)
    root.include_router(cmd_task_router)
    root.include_router(cmd_subscriptions_router)
    root.include_router(join_request_router)
    root.include_router(join_request_callbacks_router)
    root.include_router(reply_settings_router)
    root.include_router(settings_router)
    root.include_router(moderation_router)
    root.include_router(fallback_router)
    return root
