from __future__ import annotations
from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardRemove

from bot.config import AppKind, get_settings
from bot.db.session import SessionLocal
from bot.keyboards.reply import main_menu_keyboard
from bot.services.chat_member_service import is_group_admin
from bot.services.menu_button_service import configure_private_chat_menu_button, resolve_webapp_url
from bot.services.private_access_gate_service import enforce_private_access_gate
from bot.services.subscription_service import SubscriptionService
from bot.services.user_service import UserService
from bot.utils.i18n import t

router = Router(name="start")


def _main_menu_markup(
    message: Message,
    *,
    lang: str,
    show_buttons: bool,
    dashboard_url: str | None,
    app_kind: AppKind,
):
    if not show_buttons or message.chat.type != "private":
        return ReplyKeyboardRemove()
    return main_menu_keyboard(lang, dashboard_url=dashboard_url, app_kind=app_kind)


@router.message(CommandStart())
async def start_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    settings = get_settings()
    fallback = settings.default_language
    app_kind = settings.bot_app_kind
    is_subscribed = False
    async with SessionLocal() as session:
        service = UserService(session)
        if message.from_user:
            lang = await service.resolve_language(message.from_user.id, fallback=fallback)
            await service.set_language(
                tg_user_id=message.from_user.id,
                language_code=lang,
                username=message.from_user.username,
                full_name=message.from_user.full_name,
            )
            await SubscriptionService(session).ensure_free_plan(
                tg_user_id=message.from_user.id,
                username=message.from_user.username,
                full_name=message.from_user.full_name,
                language_code=message.from_user.language_code,
            )
            is_subscribed = True
        else:
            lang = fallback
    owners = set(settings.bot_owner_ids)
    allow_private_dashboard = bool(message.from_user) and (
        is_subscribed or message.from_user.id in owners
    )
    if message.chat.type == "private" and message.from_user:
        await configure_private_chat_menu_button(
            bot=message.bot,
            user_id=message.from_user.id,
            enabled=allow_private_dashboard,
            app_kind=app_kind,
        )
    webapp_url = resolve_webapp_url(app_kind)
    if await enforce_private_access_gate(message, lang):
        return
    show_buttons = await is_group_admin(message)
    if message.chat.type == "private":
        show_buttons = allow_private_dashboard
    menu_key = "agents_main_menu" if app_kind == "agents" else "main_menu"
    await message.answer(
        t("start_intro", lang),
        reply_markup=_main_menu_markup(
            message,
            lang=lang,
            show_buttons=show_buttons,
            dashboard_url=webapp_url,
            app_kind=app_kind,
        ),
    )
    if message.chat.type == "private" and not show_buttons:
        await message.answer(t("subscription_mandate_prompt", lang))
