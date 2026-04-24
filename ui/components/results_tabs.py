"""Section D of the Main Dashboard — results surfacing.

Iter 5 renders:
    - **Raw Data** tab: read-only ``st.dataframe`` of every scraped item.
    - **One tab per categorizer grouping**: exploded (1 row per matched
      category) frame rendered as read-only ``st.dataframe`` for now.
      Editable ``st.data_editor`` + pivot tables land in Iter 6.

The categorization is re-run on every page render from the currently
configured rules, so editing a grouping in Settings and coming back to the
dashboard reflects the new rules against the already-scraped items — no
re-scrape required.
"""

from __future__ import annotations

import streamlit as st

from categorizer import (
    categorize_items_to_frame,
    items_to_raw_dataframe,
)
from config import AppSettings, CategorizerGrouping
from scraper.models import NewsItem

K_RUN_ITEMS = "run_items"  # list[NewsItem] — stashed after each completed run


def stash_items(items: list[NewsItem]) -> None:
    """Main Dashboard calls this once a run completes."""
    st.session_state[K_RUN_ITEMS] = items


def get_stashed_items() -> list[NewsItem]:
    items = st.session_state.get(K_RUN_ITEMS)
    if not items:
        return []
    return list(items)


def clear_stashed_items() -> None:
    st.session_state.pop(K_RUN_ITEMS, None)


def _render_raw_tab(items: list[NewsItem]) -> None:
    df = items_to_raw_dataframe(items)
    st.caption(
        f"{len(df)} item(s) scraped total. Global exclude tokens are NOT applied here — "
        "see each grouping tab for filtered + categorized views."
    )
    st.dataframe(df, use_container_width=True, hide_index=True)


def _render_grouping_tab(
    items: list[NewsItem],
    grouping: CategorizerGrouping,
    app_settings: AppSettings,
) -> None:
    if not grouping.rules:
        st.info(
            f"Grouping **{grouping.name}** has no rules yet. Add some in "
            "**Settings → Categorization Configuration**.",
            icon="ℹ️",
        )
        return

    df = categorize_items_to_frame(
        items,
        grouping,
        global_excludes=app_settings.overall_exclude_tokens,
    )
    n_items_matched = df["Title"].nunique() if not df.empty else 0
    st.caption(
        f"{len(df)} row(s) across {n_items_matched} unique article(s) · "
        f"{len(grouping.rules)} rule(s) in this grouping"
    )
    st.dataframe(df, use_container_width=True, hide_index=True)


def render(
    groupings: list[CategorizerGrouping],
    app_settings: AppSettings,
) -> None:
    """Public entrypoint for the Main Dashboard."""
    items = get_stashed_items()

    if not items:
        st.caption("No scrape results yet. Click **Start Scraping** above to populate these tabs.")
        return

    tab_labels = ["Raw Data"] + [g.name for g in groupings]
    tabs = st.tabs(tab_labels)

    with tabs[0]:
        _render_raw_tab(items)

    for tab, grouping in zip(tabs[1:], groupings, strict=True):
        with tab:
            _render_grouping_tab(items, grouping, app_settings)


__all__ = [
    "K_RUN_ITEMS",
    "clear_stashed_items",
    "get_stashed_items",
    "render",
    "stash_items",
]
