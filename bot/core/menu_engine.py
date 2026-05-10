from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.schemas.settings import SettingSchema, SettingType
from bot.utils.i18n import t
from bot.utils.pagination import Page


class MenuEngine:
    def main_menu(self, lang: str) -> InlineKeyboardMarkup:
        kb = InlineKeyboardBuilder()
        kb.button(text=f"🛡 {t('moderation_panel', lang)}", callback_data="menu:moderation")
        kb.button(text=f"👥 {t('members', lang)}", callback_data="menu:members")
        kb.button(text=f"📊 {t('stats', lang)}", callback_data="menu:stats")
        kb.button(text=f"⚙ {t('settings', lang)}", callback_data="menu:settings")
        kb.button(text=f"📢 {t('announcements', lang)}", callback_data="menu:announcements")
        kb.button(text=f"🤖 {t('agents', lang)}", callback_data="menu:agents")
        kb.button(text=f"❓ {t('help', lang)}", callback_data="menu:help")
        kb.adjust(2, 2, 2, 1)
        return kb.as_markup()

    def section_menu(self, lang: str) -> InlineKeyboardMarkup:
        kb = InlineKeyboardBuilder()
        kb.button(text=f"⬅ {t('back', lang)}", callback_data="menu:main")
        kb.button(text=f"🏠 {t('main_menu_btn', lang)}", callback_data="menu:main")
        kb.adjust(2)
        return kb.as_markup()

    def moderation_actions_menu(self, lang: str) -> InlineKeyboardMarkup:
        kb = InlineKeyboardBuilder()
        kb.button(text=f"🚫 {t('ban_user', lang)}", callback_data="mod:ban")
        kb.button(text=f"⏳ {t('mute_user', lang)}", callback_data="mod:mute")
        kb.button(text=f"⚠ {t('warn_user', lang)}", callback_data="mod:warn")
        kb.button(text=f"🧹 {t('clean_messages', lang)}", callback_data="mod:clean")
        kb.button(text=f"🔗 {t('anti_links', lang)}", callback_data="mod:anti_links")
        kb.button(text=f"🤖 {t('anti_spam', lang)}", callback_data="mod:anti_spam")
        kb.button(text=f"📣 {t('anti_ads', lang)}", callback_data="mod:anti_ads")
        kb.button(text=f"⬅ {t('back', lang)}", callback_data="menu:main")
        kb.adjust(2, 2, 2, 2)
        return kb.as_markup()

    def quick_actions_menu(self, target_user_id: int, lang: str) -> InlineKeyboardMarkup:
        kb = InlineKeyboardBuilder()
        kb.button(text=f"🚫 {t('ban_user', lang)}", callback_data=f"quick:ban:{target_user_id}")
        kb.button(text=f"⏳ {t('mute_user', lang)}", callback_data=f"quick:mute:{target_user_id}")
        kb.button(text=f"⚠ {t('warn_user', lang)}", callback_data=f"quick:warn:{target_user_id}")
        kb.adjust(3)
        return kb.as_markup()

    def confirmation_menu(self, action: str, target_id: int, lang: str) -> InlineKeyboardMarkup:
        kb = InlineKeyboardBuilder()
        kb.button(text=f"✅ {t('confirm', lang)}", callback_data=f"confirm:{action}:{target_id}")
        kb.button(text=f"❌ {t('cancel', lang)}", callback_data="menu:main")
        kb.adjust(1)
        return kb.as_markup()

    def group_selector(self, groups: Page[dict], lang: str) -> InlineKeyboardMarkup:
        kb = InlineKeyboardBuilder()
        for group in groups.items:
            kb.button(text=group["title"], callback_data=f"group:{group['id']}:open")
        nav = []
        if groups.has_prev:
            nav.append((f"◀ {t('prev', lang)}", f"groups:{groups.page - 1}"))
        nav.append((f"{t('page', lang)} {groups.page}/{groups.pages}", "noop"))
        if groups.has_next:
            nav.append((f"{t('next', lang)} ▶", f"groups:{groups.page + 1}"))
        for title, data in nav:
            kb.button(text=title, callback_data=data)
        kb.button(text=t("back", lang), callback_data="menu:main")
        kb.adjust(1)
        if nav:
            kb.adjust(1, len(nav), 1)
        return kb.as_markup()

    def empty_group_selector(self, lang: str, add_group_url: str | None = None) -> InlineKeyboardMarkup:
        kb = InlineKeyboardBuilder()
        if add_group_url:
            kb.button(text=t("add_group", lang), url=add_group_url)
        kb.button(text=t("refresh", lang), callback_data="menu:settings")
        kb.button(text=t("back", lang), callback_data="menu:main")
        kb.adjust(1)
        return kb.as_markup()

    def categories_menu(self, categories: list[str], lang: str) -> InlineKeyboardMarkup:
        kb = InlineKeyboardBuilder()
        for category in categories:
            kb.button(text=t(category, lang), callback_data=f"category:{category}")
        kb.button(text=t("back", lang), callback_data="menu:settings")
        kb.adjust(1)
        return kb.as_markup()

    def settings_for_category(
        self,
        schemas: list[SettingSchema],
        values: dict[str, bool | int | str],
        lang: str,
    ) -> InlineKeyboardMarkup:
        kb = InlineKeyboardBuilder()
        for schema in schemas:
            value = values.get(schema.key, schema.default)
            if schema.type == SettingType.TOGGLE:
                state = t("enabled", lang) if value else t("disabled", lang)
                kb.button(
                    text=f"{t(schema.label_key, lang)}: {state}",
                    callback_data=f"setting:{schema.key}:toggle",
                )
            elif schema.type == SettingType.NUMBER:
                kb.button(
                    text=f"{t(schema.label_key, lang)}: {value}",
                    callback_data=f"setting:{schema.key}:slider",
                )
        kb.button(text=t("back", lang), callback_data="menu:categories")
        kb.adjust(1)
        return kb.as_markup()

    def numeric_slider(self, schema: SettingSchema, current: int, lang: str) -> InlineKeyboardMarkup:
        kb = InlineKeyboardBuilder()
        min_value = schema.min if schema.min is not None else 0
        max_value = schema.max if schema.max is not None else 100
        kb.button(text="-1", callback_data=f"slider:{schema.key}:{max(min_value, current - 1)}")
        kb.button(text="+1", callback_data=f"slider:{schema.key}:{min(max_value, current + 1)}")
        kb.button(text=t("back", lang), callback_data="menu:category")
        kb.adjust(2, 1)
        return kb.as_markup()

    def agent_group_selector(self, groups: Page[dict], lang: str) -> InlineKeyboardMarkup:
        kb = InlineKeyboardBuilder()
        for group in groups.items:
            kb.button(text=group["title"], callback_data=f"agent-group:{group['id']}:open")
        nav = []
        if groups.has_prev:
            nav.append((f"◀ {t('prev', lang)}", f"agent-groups:{groups.page - 1}"))
        nav.append((f"{t('page', lang)} {groups.page}/{groups.pages}", "noop"))
        if groups.has_next:
            nav.append((f"{t('next', lang)} ▶", f"agent-groups:{groups.page + 1}"))
        for title, data in nav:
            kb.button(text=title, callback_data=data)
        kb.button(text=t("back", lang), callback_data="menu:main")
        kb.adjust(1)
        if nav:
            kb.adjust(1, len(nav), 1)
        return kb.as_markup()

    def agents_menu(self, lang: str) -> InlineKeyboardMarkup:
        kb = InlineKeyboardBuilder()
        kb.button(text=f"🔗 {t('link_account', lang)}", callback_data="agents:link")
        kb.button(text=f"📋 {t('my_agents', lang)}", callback_data="agents:list")
        kb.button(text=f"⚙ {t('agent_jobs', lang)}", callback_data="agents:jobs")
        kb.button(text=f"⬅ {t('back', lang)}", callback_data="menu:agents")
        kb.button(text=f"🏠 {t('main_menu_btn', lang)}", callback_data="menu:main")
        kb.adjust(1)
        return kb.as_markup()

    def agent_jobs_menu(self, lang: str) -> InlineKeyboardMarkup:
        kb = InlineKeyboardBuilder()
        kb.button(text=f"➕ {t('create_job', lang)}", callback_data="agents:create-job")
        kb.button(text=f"⬅ {t('back', lang)}", callback_data="agents:panel")
        kb.button(text=f"🏠 {t('main_menu_btn', lang)}", callback_data="menu:main")
        kb.adjust(1)
        return kb.as_markup()
