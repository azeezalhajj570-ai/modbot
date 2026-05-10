from __future__ import annotations

from dataclasses import dataclass

from bot.services.settings_service import GroupSettingAdapter, SettingsService, parse_bool_setting, parse_int_setting


@dataclass
class ModerationSettings:
    anti_links: bool = True
    anti_spam: bool = True
    anti_ads: bool = True
    anti_spam_mute: bool = False
    anti_spam_mute_limit: int = 1
    anti_ads_mute: bool = False
    anti_ads_mute_limit: int = 1
    warn_auto_remove: bool = False
    warn_remove_limit: int = 5
    warn_auto_mute: bool = False
    warn_mute_limit: int = 3
    warn_limit: int = 3
    anti_bots: bool = False
    join_request_verify: bool = False


MODERATION_SETTING_ADAPTERS: dict[str, GroupSettingAdapter[bool | int]] = {
    "anti_links": GroupSettingAdapter(default=True, parse=parse_bool_setting),
    "anti_spam": GroupSettingAdapter(default=True, parse=parse_bool_setting),
    "anti_ads": GroupSettingAdapter(default=True, parse=parse_bool_setting),
    "anti_spam_mute": GroupSettingAdapter(default=False, parse=parse_bool_setting),
    "anti_spam_mute_limit": GroupSettingAdapter(default=1, parse=parse_int_setting),
    "anti_ads_mute": GroupSettingAdapter(default=False, parse=parse_bool_setting),
    "anti_ads_mute_limit": GroupSettingAdapter(default=1, parse=parse_int_setting),
    "warn_auto_remove": GroupSettingAdapter(default=False, parse=parse_bool_setting),
    "warn_remove_limit": GroupSettingAdapter(default=5, parse=parse_int_setting),
    "warn_auto_mute": GroupSettingAdapter(default=False, parse=parse_bool_setting),
    "warn_mute_limit": GroupSettingAdapter(default=3, parse=parse_int_setting),
    "warn_limit": GroupSettingAdapter(default=3, parse=parse_int_setting),
    "anti_bots": GroupSettingAdapter(default=False, parse=parse_bool_setting),
    "join_request_verify": GroupSettingAdapter(default=False, parse=parse_bool_setting),
}


class ModerationSettingsStore:
    def __init__(self, session) -> None:
        self.session = session
        self.settings = SettingsService(session)

    async def get_settings(self, group_id: int) -> ModerationSettings:
        values = await self.settings.get_all_typed(group_id, adapters=MODERATION_SETTING_ADAPTERS)
        return ModerationSettings(
            anti_links=bool(values["anti_links"]),
            anti_spam=bool(values["anti_spam"]),
            anti_ads=bool(values["anti_ads"]),
            anti_spam_mute=bool(values["anti_spam_mute"]),
            anti_spam_mute_limit=int(values["anti_spam_mute_limit"]),
            anti_ads_mute=bool(values["anti_ads_mute"]),
            anti_ads_mute_limit=int(values["anti_ads_mute_limit"]),
            warn_auto_remove=bool(values["warn_auto_remove"]),
            warn_remove_limit=int(values["warn_remove_limit"]),
            warn_auto_mute=bool(values["warn_auto_mute"]),
            warn_mute_limit=int(values["warn_mute_limit"]),
            warn_limit=int(values["warn_limit"]),
            anti_bots=bool(values["anti_bots"]),
            join_request_verify=bool(values["join_request_verify"]),
        )

    async def is_feature_enabled(self, group_id: int, feature_key: str, *, default: bool = True) -> bool:
        settings = await self.get_settings(group_id)
        value = getattr(settings, feature_key, None)
        if isinstance(value, bool):
            return value
        return default
