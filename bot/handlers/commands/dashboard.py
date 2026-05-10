from __future__ import annotations

import structlog
from urllib.parse import urlsplit, urlunsplit

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardRemove

from bot.config import get_settings
from bot.db.session import SessionLocal
from bot.keyboards.inline import open_dashboard_inline_keyboard
from bot.keyboards.reply import empty_groups_keyboard, groups_keyboard, language_keyboard, main_menu_keyboard
from bot.services.chat_member_service import is_group_admin
from bot.services.group_service import GroupService
from bot.services.menu_button_service import configure_private_chat_menu_button, resolve_webapp_url
from bot.services.subscription_service import SubscriptionService
from bot.services.user_service import UserService
from bot.handlers.menu.states import SettingsFlow
from bot.utils.i18n import t

router = Router(name="dashboard_commands")
logger = structlog.get_logger(__name__)


async def _resolve_lang(message: Message) -> str:
    fallback = get_settings().default_language
    if not message.from_user:
        return fallback
    async with SessionLocal() as session:
        return await UserService(session).resolve_language(message.from_user.id, fallback=fallback)


def _webapp_url() -> str | None:
    return resolve_webapp_url()


def _webapp_route_url(route: str | None = None) -> str | None:
    base_url = _webapp_url()
    if not base_url or not route:
        return base_url
    parts = urlsplit(base_url)
    fragment = route[1:] if route.startswith("#") else route
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, fragment))


def _normalize_language_arg(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.strip().lower()
    if value in {"en", "english"}:
        return "en"
    if value in {"ar", "arabic", "arab", "العربية", "عربي", "arabia"}:
        return "ar"
    return None


async def _set_user_language(message: Message, *, new_lang: str) -> None:
    if not message.from_user:
        return
    async with SessionLocal() as session:
        await UserService(session).set_language(
            tg_user_id=message.from_user.id,
            language_code=new_lang,
            username=message.from_user.username,
            full_name=message.from_user.full_name,
        )


def _group_member_hide_markup(message: Message, show_buttons: bool):
    if show_buttons and message.chat.type == "private":
        return None
    return ReplyKeyboardRemove()


def _main_menu_markup(message: Message, *, lang: str, show_buttons: bool, dashboard_url: str | None, app_kind: str | None = None):
    if not show_buttons or message.chat.type != "private":
        return ReplyKeyboardRemove()
    return main_menu_keyboard(lang, dashboard_url=dashboard_url, app_kind=app_kind)


async def _can_show_dashboard(message: Message) -> bool:
    show_buttons = await is_group_admin(message)
    if message.chat.type != "private" or not message.from_user:
        return show_buttons

    settings = get_settings()
    async with SessionLocal() as session:
        is_subscribed = await SubscriptionService(session).has_active_subscription(tg_user_id=message.from_user.id)
    allowed = is_subscribed or message.from_user.id in set(settings.bot_owner_ids)
    await configure_private_chat_menu_button(
        bot=message.bot,
        user_id=message.from_user.id,
        enabled=allowed,
        app_kind=settings.bot_app_kind,
    )
    return allowed


async def _open_private_settings(message: Message, state: FSMContext, *, lang: str) -> None:
    async with SessionLocal() as session:
        groups_page = await GroupService(session).list_admin_groups(message.from_user.id, page=1, page_size=10)

    await state.set_state(SettingsFlow.selecting_group)
    await state.update_data(group_page=1, group_items=groups_page.items)

    if groups_page.total == 0:
        await message.answer(
            t("select_group", lang),
            reply_markup=empty_groups_keyboard(lang, include_tabs=False),
        )
        return

    await message.answer(
        t("select_group", lang),
        reply_markup=groups_keyboard(groups_page, lang, include_tabs=False),
    )


@router.message(Command("dashboard"))
async def dashboard_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    settings = get_settings()
    lang = await _resolve_lang(message)
    webapp_url = _webapp_url()
    show_buttons = await _can_show_dashboard(message)
    logger.info(
        "dashboard_handler_invoked",
        user_id=message.from_user.id if message.from_user else None,
        chat_id=message.chat.id,
        chat_type=message.chat.type,
        webapp_url=webapp_url,
        show_buttons=show_buttons,
    )
    if message.chat.type == "private" and not show_buttons:
        await message.answer(
            t("subscription_mandate_prompt", lang),
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    if not webapp_url:
        await message.answer(
            t("dashboard_not_configured", lang),
            reply_markup=_group_member_hide_markup(message, show_buttons),
        )
        return

    menu_key = "agents_main_menu" if settings.bot_app_kind == "agents" else "main_menu"
    await message.answer(
        t(menu_key, lang),
        reply_markup=_main_menu_markup(
            message,
            lang=lang,
            show_buttons=show_buttons,
            dashboard_url=webapp_url,
            app_kind=settings.bot_app_kind,
        ),
    )


@router.message(Command("scraper"))
async def scraper_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    lang = await _resolve_lang(message)
    webapp_url = _webapp_route_url("#/scraper")
    show_buttons = await _can_show_dashboard(message)
    if message.chat.type == "private" and not show_buttons:
        await message.answer(
            t("subscription_mandate_prompt", lang),
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    if not webapp_url:
        await message.answer(
            t("dashboard_not_configured", lang),
            reply_markup=_group_member_hide_markup(message, show_buttons),
        )
        return

    await message.answer(
        t("scraper_open_prompt", lang),
        reply_markup=(
            open_dashboard_inline_keyboard(f"🕷 {t('open_scraper', lang)}", webapp_url)
            if show_buttons
            else _group_member_hide_markup(message, show_buttons)
        ),
    )


@router.message(Command("settings"))
async def settings_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    lang = await _resolve_lang(message)
    webapp_url = _webapp_url()
    show_buttons = await _can_show_dashboard(message)
    logger.info(
        "settings_handler_invoked",
        user_id=message.from_user.id if message.from_user else None,
        chat_id=message.chat.id,
        chat_type=message.chat.type,
        webapp_url=webapp_url,
        show_buttons=show_buttons,
    )
    if message.chat.type == "private" and not show_buttons:
        await message.answer(
            t("subscription_mandate_prompt", lang),
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    if message.chat.type == "private":
        await _open_private_settings(message, state, lang=lang)
        return
    if not webapp_url:
        await message.answer(
            t("dashboard_not_configured", lang),
            reply_markup=_group_member_hide_markup(message, show_buttons),
        )
        return

    await message.answer(
        t("settings_open_prompt", lang),
        reply_markup=(
            open_dashboard_inline_keyboard(f"⚙ {t('open_settings', lang)}", webapp_url)
            if show_buttons
            else _group_member_hide_markup(message, show_buttons)
        ),
    )


@router.message(Command("help"))
async def help_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    settings = get_settings()
    lang = await _resolve_lang(message)
    webapp_url = _webapp_url()
    show_buttons = await _can_show_dashboard(message)
    help_key = "agents_help_text" if settings.bot_app_kind == "agents" else "help_text"
    await message.answer(
        t(help_key, lang) if show_buttons or message.chat.type != "private" else t("subscription_mandate_prompt", lang),
        reply_markup=_main_menu_markup(
            message,
            lang=lang,
            show_buttons=show_buttons,
            dashboard_url=webapp_url,
            app_kind=settings.bot_app_kind,
        ),
    )


@router.message(Command("lang"))
@router.message(Command("language"))
async def language_handler(message: Message, state: FSMContext) -> None:
    lang = await _resolve_lang(message)
    parts = (message.text or "").split(maxsplit=1)
    selected = _normalize_language_arg(parts[1] if len(parts) > 1 else None)

    if selected is not None:
        await _set_user_language(message, new_lang=selected)
        await state.clear()
        await message.answer(
            t("language_updated", selected),
            reply_markup=main_menu_keyboard(selected, dashboard_url=_webapp_url()) if message.chat.type == "private" else ReplyKeyboardRemove(),
        )
        return

    if message.chat.type != "private":
        await message.answer(t("choose_language", lang), reply_markup=ReplyKeyboardRemove())
        return

    await state.set_state(SettingsFlow.language_menu)
    await message.answer(t("choose_language", lang), reply_markup=language_keyboard(lang))
