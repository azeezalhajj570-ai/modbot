from bot.schemas.settings import SettingSchema, SettingType

SETTINGS_SCHEMA = [
    SettingSchema(
        key="semantic_assistant_service_name",
        type=SettingType.TEXT,
        category="advanced",
        label_key="semantic_assistant_service_name",
        default="",
    ),
    SettingSchema(
        key="semantic_assistant_resource_scope",
        type=SettingType.TEXT,
        category="advanced",
        label_key="semantic_assistant_resource_scope",
        default="",
    ),
    SettingSchema(
        key="semantic_assistant_reply_prefix",
        type=SettingType.TEXT,
        category="advanced",
        label_key="semantic_assistant_reply_prefix",
        default="",
    ),
    SettingSchema(
        key="semantic_assistant_top_k",
        type=SettingType.NUMBER,
        category="advanced",
        label_key="semantic_assistant_top_k",
        min=1,
        max=10,
        default=3,
    ),
]
