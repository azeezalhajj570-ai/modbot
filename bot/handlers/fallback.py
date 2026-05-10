from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message, ReplyKeyboardRemove
from sqlalchemy import select
import structlog

from bot.config import get_settings
from bot.db.models import Group
from bot.keyboards.reply import main_menu_keyboard
from bot.db.session import SessionLocal
from bot.services.group_service import canonical_tg_group_id, sync_group_admin_roles, tg_group_id_candidates, upsert_group
from bot.services.menu_button_service import configure_private_chat_menu_button, resolve_webapp_url
from bot.services.private_access_gate_service import enforce_private_access_gate
from bot.services.subscription_service import SubscriptionService
from bot.services.user_service import UserService
from bot.utils.i18n import t

router = Router(name="fallback")
logger = structlog.get_logger(__name__)


@router.message(F.chat.type == "private")
async def private_fallback(message: Message) -> None:
    fallback = get_settings().default_language
    lang = fallback
    owners = set(get_settings().bot_owner_ids)
    async with SessionLocal() as session:
        if message.from_user:
            lang = await UserService(session).resolve_language(message.from_user.id, fallback=fallback)
            await SubscriptionService(session).ensure_free_plan(
                tg_user_id=message.from_user.id,
                username=message.from_user.username,
                full_name=message.from_user.full_name,
                language_code=message.from_user.language_code,
            )
        is_subscribed = bool(message.from_user) and await SubscriptionService(session).has_active_subscription(
            tg_user_id=message.from_user.id
        )
    if await enforce_private_access_gate(message, lang):
        return
    can_open_dashboard = bool(message.from_user) and (is_subscribed or message.from_user.id in owners)
    logger.info(
        "private_fallback_triggered",
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else None,
        text=message.text or message.caption or "",
        lang=lang,
        can_open_dashboard=can_open_dashboard,
    )
    if message.from_user:
        await configure_private_chat_menu_button(
            bot=message.bot,
            user_id=message.from_user.id,
            enabled=can_open_dashboard,
        )
    dashboard_url = resolve_webapp_url()
    await message.answer(
        t("main_menu", lang),
        reply_markup=main_menu_keyboard(lang, dashboard_url=dashboard_url)
        if can_open_dashboard
        else ReplyKeyboardRemove(),
    )


@router.callback_query()
async def callback_fallback(call: CallbackQuery) -> None:
    logger.warning(
        "callback_fallback_triggered",
        user_id=call.from_user.id if call.from_user else None,
        chat_id=call.message.chat.id if call.message else None,
        callback_data=call.data,
        message_text=call.message.text if call.message else None,
    )
    await call.answer("Unhandled button action.", show_alert=True)


@router.my_chat_member()
async def my_chat_member_fallback(event: ChatMemberUpdated) -> None:
    if event.chat.type not in {"group", "supergroup", "channel"}:
        return

    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status
    active_statuses = {"member", "administrator"}

    logger.info(
        "my_chat_member_fallback",
        chat_id=event.chat.id,
        chat_type=event.chat.type,
        title=event.chat.title,
        old_status=old_status,
        new_status=new_status,
        from_user_id=event.from_user.id if event.from_user else None,
    )

    async with SessionLocal() as session:
        if new_status in active_statuses:
            group = await upsert_group(
                session,
                tg_group_id=event.chat.id,
                title=event.chat.title,
                is_active=True,
            )
            if event.from_user and group.registered_by_user_id is None:
                group.registered_by_user_id = event.from_user.id
            logger.info(
                "group_activated_via_my_chat_member",
                group_id=group.id,
                tg_group_id=group.tg_group_id,
                title=group.title,
            )
            await sync_group_admin_roles(session, bot=event.bot, group=group, fallback_actor=event.from_user)
        elif old_status in active_statuses and new_status in {"left", "kicked"}:
            rows = (
                await session.execute(select(Group).where(Group.tg_group_id.in_(tg_group_id_candidates(event.chat.id))))
            ).scalars().all()
            group = next((item for item in rows if canonical_tg_group_id(item.tg_group_id) == canonical_tg_group_id(event.chat.id)), None)
            if group:
                group.is_active = False
                logger.info(
                    "group_deactivated_via_my_chat_member",
                    group_id=group.id,
                    tg_group_id=group.tg_group_id,
                    title=group.title,
                )

        await session.commit()


@router.chat_member()
async def chat_member_fallback(_event: ChatMemberUpdated) -> None:
    return


@router.edited_message()
async def edited_message_fallback(_message: Message) -> None:
    return
