"""FAQ plugin settings schema."""

from bot.schemas.settings import SettingSchema

SETTINGS_SCHEMA = [
    SettingSchema(
        key="faq_enabled",
        type="toggle",
        label_key="settings.faq_enabled",
        default=False,
        category="automation",
    ),
    SettingSchema(
        key="faq_safe_mode",
        type="toggle",
        label_key="settings.faq_safe_mode",
        default=True,
        category="automation",
    ),
]
