from __future__ import annotations

from bot.utils.i18n import t


def build_rule_notice(lang: str, rule_key: str, **fmt: object) -> str:
    title = t("moderation_notice_title", lang)
    body = t(f"{rule_key}_notice", lang, **fmt)
    return f"{title}\n{body}"
