"""Typed ``st.session_state`` accessors.

Centralising the keys here prevents the classic Streamlit bug where two files
disagree on a key name and silently read ``None``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import streamlit as st

# --- Session-state keys ---------------------------------------------------- #

K_SOURCES = "sources_cache"
K_GROUPINGS = "groupings_cache"
K_APP_SETTINGS = "app_settings_cache"
K_TIME_RANGE = "time_range"
K_SELECTED_SOURCES = "selected_sources"
K_PAGE_RANGES = "page_ranges"
K_SCRAPE_JOB = "scrape_job"
K_SCRAPE_PROGRESS = "scrape_progress"
K_RESULTS_DF = "results_df"


@dataclass
class TimeRange:
    start_month: int = 1
    start_year: int = 2026
    end_month: int = 12
    end_year: int = 2026


@dataclass
class ScrapeProgress:
    """Thread-safe-readable snapshot of the currently running scrape job."""

    overall: float = 0.0
    per_source: dict[str, float] = field(default_factory=dict)
    messages: list[str] = field(default_factory=list)
    done: bool = False


def ensure_defaults() -> None:
    """Populate session_state with default scalars on first run.

    Safe to call on every rerun; only sets keys that are missing.
    """
    defaults: dict[str, Any] = {
        K_TIME_RANGE: TimeRange(),
        K_SELECTED_SOURCES: set(),
        K_PAGE_RANGES: {},
        K_SCRAPE_JOB: None,
        K_SCRAPE_PROGRESS: ScrapeProgress(),
        K_RESULTS_DF: None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


__all__ = [
    "K_APP_SETTINGS",
    "K_GROUPINGS",
    "K_PAGE_RANGES",
    "K_RESULTS_DF",
    "K_SCRAPE_JOB",
    "K_SCRAPE_PROGRESS",
    "K_SELECTED_SOURCES",
    "K_SOURCES",
    "K_TIME_RANGE",
    "ScrapeProgress",
    "TimeRange",
    "ensure_defaults",
]
