"""Typed, validated, atomic config load/save.

All schemas are declared as ``pydantic`` models so we get parse-time validation
and IDE autocomplete across the rest of the codebase. Writes go through
``utils.io.atomic_write_text`` so a crash mid-write can never corrupt an
existing config file.
"""

from __future__ import annotations

from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from config.paths import app_settings_path, categorizers_path, sources_path
from utils.io import atomic_write_text, read_text_or_default

# --------------------------------------------------------------------------- #
# Scraper source schema
# --------------------------------------------------------------------------- #

PaginationType = Literal["url_params", "infinite_scroll", "click_next"]
ScrapeLayer = Literal[1, 2, 3, 4]


class ScraperSelectors(BaseModel):
    """CSS/XPath selectors used to pull items out of a listing page."""

    model_config = ConfigDict(extra="forbid")

    container: str = Field(..., description="Selector for one article row.")
    title: str
    link: str
    date: str
    next_button: str | None = Field(
        default=None,
        description="Only required when pagination_type == 'click_next'.",
    )


class SleepRange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min: float = Field(default=1.0, ge=0.0)
    max: float = Field(default=3.0, ge=0.0)

    @field_validator("max")
    @classmethod
    def _max_ge_min(cls, v: float, info):  # type: ignore[no-untyped-def]
        mn = info.data.get("min", 0.0)
        if v < mn:
            raise ValueError("sleep.max must be >= sleep.min")
        return v


class ScrapeSource(BaseModel):
    """A single configured news portal."""

    model_config = ConfigDict(extra="forbid")

    name: str
    pagination_type: PaginationType = "url_params"
    url_template: str
    selectors: ScraperSelectors
    avg_page_per_month: int = Field(default=30, ge=1)
    sleep: SleepRange = Field(default_factory=SleepRange)
    max_retries: int = Field(default=3, ge=0)
    enabled_layers: list[ScrapeLayer] = Field(default_factory=lambda: [1, 3])
    scrolls_per_page: int = Field(
        default=1,
        ge=1,
        description="Only used when pagination_type == 'infinite_scroll'.",
    )
    enabled: bool = True

    @field_validator("enabled_layers")
    @classmethod
    def _layers_non_empty(cls, v: list[ScrapeLayer]) -> list[ScrapeLayer]:
        if not v:
            raise ValueError("enabled_layers cannot be empty")
        return sorted(set(v))


# --------------------------------------------------------------------------- #
# Categorizer schema
# --------------------------------------------------------------------------- #


class CategoryRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    include_tokens: list[str] = Field(default_factory=list)
    exclude_tokens: list[str] = Field(default_factory=list)


class CategorizerGrouping(BaseModel):
    """A named collection of category rules (e.g. 'GDP Sector')."""

    model_config = ConfigDict(extra="forbid")

    name: str
    rules: list[CategoryRule] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# App-level settings
# --------------------------------------------------------------------------- #


class AppSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overall_exclude_tokens: list[str] = Field(default_factory=list)
    default_min_sleep: float = 1.5
    default_max_sleep: float = 4.0
    default_max_retries: int = 3
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


# --------------------------------------------------------------------------- #
# Load / save helpers
# --------------------------------------------------------------------------- #

import json  # noqa: E402  (kept at bottom to avoid confusing the schema block)


def load_sources() -> list[ScrapeSource]:
    raw = read_text_or_default(sources_path(), default='{"sources": []}')
    data = json.loads(raw)
    return [ScrapeSource.model_validate(item) for item in data.get("sources", [])]


def save_sources(sources: list[ScrapeSource]) -> None:
    payload = {"sources": [s.model_dump(mode="json") for s in sources]}
    atomic_write_text(sources_path(), json.dumps(payload, indent=2, ensure_ascii=False))


def load_categorizers() -> list[CategorizerGrouping]:
    raw = read_text_or_default(categorizers_path(), default='{"groupings": []}')
    data = json.loads(raw)
    return [CategorizerGrouping.model_validate(g) for g in data.get("groupings", [])]


def save_categorizers(groupings: list[CategorizerGrouping]) -> None:
    payload = {"groupings": [g.model_dump(mode="json") for g in groupings]}
    atomic_write_text(categorizers_path(), json.dumps(payload, indent=2, ensure_ascii=False))


def load_app_settings() -> AppSettings:
    raw = read_text_or_default(app_settings_path(), default="")
    if not raw.strip():
        return AppSettings()
    data = yaml.safe_load(raw) or {}
    return AppSettings.model_validate(data)


def save_app_settings(settings: AppSettings) -> None:
    atomic_write_text(
        app_settings_path(),
        yaml.safe_dump(settings.model_dump(mode="json"), sort_keys=False),
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
