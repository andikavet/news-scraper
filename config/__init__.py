"""Config layer — single source of truth for scraper + categorizer definitions.

Only this package is allowed to touch the config JSON/YAML files on disk.
"""

from config.store import (
    AppSettings,
    CategorizerGrouping,
    CategoryRule,
    PaginationType,
    ScrapeLayer,
    ScraperSelectors,
    ScrapeSource,
    SleepRange,
    load_app_settings,
    load_categorizers,
    load_sources,
    save_app_settings,
    save_categorizers,
    save_sources,
)

__all__ = [
    "AppSettings",
    "CategorizerGrouping",
    "CategoryRule",
    "PaginationType",
    "ScrapeLayer",
    "ScrapeSource",
    "ScraperSelectors",
    "SleepRange",
    "load_app_settings",
    "load_categorizers",
    "load_sources",
    "save_app_settings",
    "save_categorizers",
    "save_sources",
]
