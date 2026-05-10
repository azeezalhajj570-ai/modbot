from __future__ import annotations

from sqlalchemy import select

from bot.core.runtime.events import RuntimeEvent
from bot.core.runtime.guards import GuardDecision
from bot.core.runtime.moderation import FeatureEnabledGuard
from bot.db.models import GroupSetting
from bot.services.moderation_settings_store import ModerationSettingsStore
from bot.services.settings_service import GroupSettingAdapter, SettingsService, parse_bool_setting, parse_int_setting


async def test_moderation_settings_store_applies_defaults_and_typed_values(db_session, seeded_group) -> None:
    db_session.add(GroupSetting(group_id=seeded_group["group_id"], key="anti_spam", value={"value": False}))
    db_session.add(GroupSetting(group_id=seeded_group["group_id"], key="anti_ads_mute_limit", value={"value": "4"}))
    db_session.add(GroupSetting(group_id=seeded_group["group_id"], key="warn_limit", value={"value": 6}))
    await db_session.commit()

    settings = await ModerationSettingsStore(db_session).get_settings(seeded_group["group_id"])

    assert settings.anti_links is True
    assert settings.anti_spam is False
    assert settings.anti_ads_mute_limit == 4
    assert settings.warn_limit == 6
    assert settings.warn_remove_limit == 5


async def test_feature_enabled_guard_uses_moderation_settings_store(db_session, seeded_group) -> None:
    db_session.add(GroupSetting(group_id=seeded_group["group_id"], key="anti_spam", value={"value": False}))
    await db_session.commit()

    guard = FeatureEnabledGuard(db_session)
    result = await guard.evaluate(
        RuntimeEvent(name="moderation.message_flagged", group_id=seeded_group["group_id"], actor_user_id=seeded_group["user_id"], payload={"feature_key": "anti_spam"}),
        action=None,
    )

    assert result.decision == GuardDecision.DENY
    assert result.reason == "anti_spam disabled"


async def test_settings_service_unwrap_value_supports_internal_views(db_session, seeded_group) -> None:
    db_session.add(
        GroupSetting(
            group_id=seeded_group["group_id"],
            key="raw_passthrough",
            value={"value": {"destination": "@alerts"}},
        )
    )
    await db_session.commit()

    stored = (
        await db_session.execute(
            select(GroupSetting.value).where(
                GroupSetting.group_id == seeded_group["group_id"],
                GroupSetting.key == "raw_passthrough",
            )
        )
    ).scalar_one()

    assert ModerationSettingsStore(db_session).settings.unwrap_value(stored) == {"destination": "@alerts"}


async def test_settings_service_typed_adapters_parse_wrapped_legacy_values(db_session, seeded_group) -> None:
    db_session.add(GroupSetting(group_id=seeded_group["group_id"], key="anti_bots", value={"value": "false"}))
    db_session.add(GroupSetting(group_id=seeded_group["group_id"], key="warn_limit", value={"value": "7"}))
    await db_session.commit()

    settings = SettingsService(db_session)
    anti_bots = await settings.get_typed(
        seeded_group["group_id"],
        "anti_bots",
        adapter=GroupSettingAdapter(default=True, parse=parse_bool_setting),
    )
    warn_limit = await settings.get_typed(
        seeded_group["group_id"],
        "warn_limit",
        adapter=GroupSettingAdapter(default=3, parse=parse_int_setting),
    )

    assert anti_bots is False
    assert warn_limit == 7
