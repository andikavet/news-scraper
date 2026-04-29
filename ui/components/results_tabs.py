"""Section D of the Main Dashboard — results surfacing.

Iter 5 rendered Raw Data + per-grouping exploded frames as read-only dataframes.
Iter 6 upgrades to:
    - Each grouping tab is now an editable ``st.data_editor`` — the user can
      correct a miscategorized row, delete noise, or rename a Source inline.
    - Below each editor sits a **Source × Category** pivot table that shows
      every configured category as a column (reindexed on full category list)
      even if zero rows matched. Empty categories are visible 0-columns.
    - An **Update Pivot** button per grouping re-builds the pivot from the
      **currently-edited** data_editor state. Until clicked, the pivot stays
      pinned to the last snapshot so keystroke-level edits don't thrash.

The initial auto-categorization still runs from the currently-configured rules
on every page render, so editing a grouping in Settings and coming back
reflects the new rules against the already-scraped items — no re-scrape
required (preserved from Iter 5).

Session-state keys used here:
    - K_RUN_ITEMS: list[NewsItem] stashed after a completed run (Iter 5).
    - K_EDITOR_FRAME_PREFIX + grouping name: the user's edited frame for
      that grouping, carried across reruns so their edits don't get
      clobbered on every fragment tick.
    - K_PIVOT_SNAPSHOT_PREFIX + grouping name: the last pivot the user
      explicitly asked to build via the Update Pivot button.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from categorizer import (
    GROUPING_COLUMNS,
    aggregation_to_html,
    build_aggregation,
    categorize_items_to_frame,
    items_to_raw_dataframe,
)
from config import AppSettings, CategorizerGrouping
from scraper.models import NewsItem

K_RUN_ITEMS = "run_items"  # list[NewsItem] — stashed after each completed run
K_EDITOR_FRAME_PREFIX = "results_editor_frame__"
K_EDITOR_AUTO_SOURCE_PREFIX = "results_editor_auto_source__"
K_PIVOT_SNAPSHOT_PREFIX = "results_pivot_snapshot__"
K_QUARTER_PIVOT_SNAPSHOT_PREFIX = "results_quarter_pivot_snapshot__"


def stash_items(items: list[NewsItem]) -> None:
    """Main Dashboard calls this once a run completes."""
    st.session_state[K_RUN_ITEMS] = items
    # Any previously-cached editor frames / pivot snapshots reflect the *old*
    # items; wipe them so the new run starts from a fresh auto-categorization.
    _clear_all_grouping_caches()


def get_stashed_items() -> list[NewsItem]:
    items = st.session_state.get(K_RUN_ITEMS)
    if not items:
        return []
    return list(items)


def clear_stashed_items() -> None:
    st.session_state.pop(K_RUN_ITEMS, None)
    _clear_all_grouping_caches()


def _clear_all_grouping_caches() -> None:
    for key in list(st.session_state.keys()):
        if isinstance(key, str) and (
            key.startswith(K_EDITOR_FRAME_PREFIX)
            or key.startswith(K_EDITOR_AUTO_SOURCE_PREFIX)
            or key.startswith(K_PIVOT_SNAPSHOT_PREFIX)
            or key.startswith(K_QUARTER_PIVOT_SNAPSHOT_PREFIX)
        ):
            st.session_state.pop(key, None)


def _editor_frame_key(grouping_name: str) -> str:
    return K_EDITOR_FRAME_PREFIX + grouping_name


def _auto_source_key(grouping_name: str) -> str:
    """Hash of the auto-categorization inputs that produced the editor frame.

    If rules or global excludes change (edited in Settings), this hash
    changes and we re-seed the editor from fresh auto-categorization rather
    than carrying stale edits forward.
    """
    return K_EDITOR_AUTO_SOURCE_PREFIX + grouping_name


def _pivot_snapshot_key(grouping_name: str) -> str:
    return K_PIVOT_SNAPSHOT_PREFIX + grouping_name


def _quarter_pivot_snapshot_key(grouping_name: str) -> str:
    return K_QUARTER_PIVOT_SNAPSHOT_PREFIX + grouping_name


def _auto_source_fingerprint(
    grouping: CategorizerGrouping, app_settings: AppSettings, items_len: int
) -> tuple:
    """Small tuple that changes iff the auto-categorization inputs changed."""
    rule_fp = tuple(
        (r.category, tuple(r.include_tokens), tuple(r.exclude_tokens)) for r in grouping.rules
    )
    return (
        items_len,
        rule_fp,
        tuple(app_settings.overall_exclude_tokens),
    )


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

    auto_df = categorize_items_to_frame(
        items,
        grouping,
        global_excludes=app_settings.overall_exclude_tokens,
    )
    fingerprint = _auto_source_fingerprint(grouping, app_settings, len(items))
    auto_source_k = _auto_source_key(grouping.name)
    editor_k = _editor_frame_key(grouping.name)

    # (Re-)seed the editor frame when rules change or on first render.
    if st.session_state.get(auto_source_k) != fingerprint:
        st.session_state[auto_source_k] = fingerprint
        st.session_state[editor_k] = auto_df.copy()
        # Any previous aggregation snapshots are now stale.
        st.session_state.pop(_pivot_snapshot_key(grouping.name), None)
        st.session_state.pop(_quarter_pivot_snapshot_key(grouping.name), None)

    edited_df: pd.DataFrame = st.session_state[editor_k]
    n_items_matched = edited_df["Title"].nunique() if not edited_df.empty else 0
    st.caption(
        f"{len(edited_df)} row(s) across {n_items_matched} unique article(s) · "
        f"{len(grouping.rules)} rule(s) in this grouping"
    )

    new_edited = st.data_editor(
        edited_df,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        key=f"data_editor__{grouping.name}",
        column_config={
            "Category": st.column_config.TextColumn("Category", required=True),
            "Date": st.column_config.TextColumn("Date"),
            "Source": st.column_config.TextColumn("Source", required=True),
            "Title": st.column_config.TextColumn("Title", width="large"),
            "Link": st.column_config.LinkColumn("Link"),
            "Page": st.column_config.NumberColumn("Page", min_value=1, step=1),
        },
    )
    # Streamlit already rerenders on every edit; we persist the latest
    # snapshot so the frame survives reruns triggered by other widgets.
    st.session_state[editor_k] = new_edited

    st.markdown("##### Aggregation")
    st.caption(
        "Rows show **every category** in this grouping (sorted ascending). "
        "Each cell is a numbered list of the actual article fields — newlines "
        "are preserved. **Update Aggregation** rebuilds both the quarterly "
        "and monthly tables from the currently-edited rows above."
    )
    btn_col, _ = st.columns([0.22, 1])
    with btn_col:
        update_clicked = st.button(
            "Update Aggregation",
            key=f"update_pivot__{grouping.name}",
            use_container_width=True,
            help=(
                "Rebuild both the Quarterly and Monthly aggregation tables "
                "from the currently-edited rows above."
            ),
        )

    pivot_snap_k = _pivot_snapshot_key(grouping.name)
    quarter_snap_k = _quarter_pivot_snapshot_key(grouping.name)
    # A single click refreshes BOTH frames so the two tables never disagree.
    if update_clicked or pivot_snap_k not in st.session_state:
        st.session_state[pivot_snap_k] = build_aggregation(new_edited, grouping, period="month")
    if update_clicked or quarter_snap_k not in st.session_state:
        st.session_state[quarter_snap_k] = build_aggregation(new_edited, grouping, period="quarter")

    quarter_df: pd.DataFrame = st.session_state[quarter_snap_k]
    pivot_df: pd.DataFrame = st.session_state[pivot_snap_k]

    # Quarterly table rendered ABOVE the monthly one per the spec.
    with st.expander("Tabel Triwulanan (Quarterly — Q1…Q4)", expanded=True):
        if quarter_df.empty or len(quarter_df.columns) == 0:
            st.caption(
                "No dated rows to aggregate yet — edit the table above or "
                "click **Update Aggregation** after a scrape produces dated items."
            )
        else:
            st.markdown(aggregation_to_html(quarter_df), unsafe_allow_html=True)

    with st.expander("Tabel Bulanan (Monthly)", expanded=True):
        if pivot_df.empty or len(pivot_df.columns) == 0:
            st.caption(
                "No dated rows to aggregate yet — edit the table above or "
                "click **Update Aggregation** after a scrape produces dated items."
            )
        else:
            # `st.dataframe` collapses `\n` into a single visual line; we
            # render an HTML table whose CSS has `white-space: pre-wrap`
            # so each numbered-list cell renders across multiple lines.
            st.markdown(aggregation_to_html(pivot_df), unsafe_allow_html=True)


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
    "GROUPING_COLUMNS",
    "K_EDITOR_FRAME_PREFIX",
    "K_PIVOT_SNAPSHOT_PREFIX",
    "K_QUARTER_PIVOT_SNAPSHOT_PREFIX",
    "K_RUN_ITEMS",
    "clear_stashed_items",
    "get_stashed_items",
    "render",
    "stash_items",
]
