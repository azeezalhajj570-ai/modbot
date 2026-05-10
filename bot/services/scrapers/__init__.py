def __getattr__(name):
    if name == "ScraperService":
        from bot.services.scraper_service import ScraperService
        return ScraperService
    if name == "canonical_tg_group_id":
        from bot.services.group_service import canonical_tg_group_id
        return canonical_tg_group_id
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["ScraperService", "canonical_tg_group_id"]
