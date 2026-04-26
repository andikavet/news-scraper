"""Main Page — Scraping Dashboard.

Iteration 4 wires the time-range picker, source selector, and live
progress panel together. Clicking "Start Scraping" kicks off the engine
on a background thread (via ``utils.async_bridge.start_engine_thread``)
so the UI stays responsive; the progress panel polls the bus and
auto-refreshes via an ``st.fragment``.

Iteration 5 adds section D (Results): a Raw Data tab and one tab per
categorizer grouping, with multi-category row explosion. Editable
tables + pivots arrive in Iter 6.
"""

from __future__ import annotations

import streamlit as st

from config import load_app_settings, load_categorizers, load_sources
from scraper.engine import EngineRunSpec
from ui.components import (
    export_panel,
    progress_panel,
    results_tabs,
    run_history_panel,
    source_selector,
    time_range,
)
from ui.components.progress_panel import K_JOB_HANDLE
from ui.state import ensure_defaults
from utils.async_bridge import start_engine_thread


def _start_scrape(
    selections: list[source_selector.SourceSelection], tr: time_range.TimeRangeSelection
) -> bool:
    picked = [s for s in selections if s.selected]
    if not picked:
        st.warning("Select at least one source before starting.", icon="⚠️")
        return False
    if tr.start > tr.end:
        st.warning("Time range is inverted — fix the start/end before running.", icon="⚠️")
        return False

    # Each source carries its own (start_page, end_page) envelope through
    # ``EngineRunSpec.per_source_pages`` so a source with auto-calculated
    # ``end_page=3`` no longer shares a ``/10`` denominator with a source
    # that was auto-set to ``end_page=10``. The top-level bounds remain
    # as defaults (used by code paths that don't go through
    # ``bounds_for``) — computed from the widest envelope so they are
    # always at least as permissive as the per-source overrides.
    per_source: dict[str, tuple[int, int]] = {
        s.source.name: (s.start_page, s.end_page) for s in picked
    }
    default_start = min(s.start_page for s in picked)
    default_end = max(s.end_page for s in picked)
    if any(end < start for (start, end) in per_source.values()):
        st.error("End page is before start page for at least one source — nothing to do.")
        return False

    spec = EngineRunSpec(
        sources=[s.source for s in picked],
        start_page=default_start,
        end_page=default_end,
        time_range_start=tr.start,
        time_range_end=tr.end,
        per_source_pages=per_source,
    )
    progress_panel.reset_snapshot()
    # Clear previous-run items so the results section doesn't show stale data
    # once the new run starts emitting events.
    results_tabs.clear_stashed_items()
    st.session_state[K_JOB_HANDLE] = start_engine_thread(spec)
    return True


def _collect_items_if_finished() -> None:
    """Stash NewsItems from the most recent run once it finishes.

    The progress panel owns its own snapshot; we piggyback on the JobHandle
    to pull the results exactly once (the handle returns a plain list, not
    a generator, so repeated reads are fine but wasteful).
    """
    handle = st.session_state.get(K_JOB_HANDLE)
    if handle is None or handle.is_running():
        return
    results = handle.results
    if results is None:
        return
    # Already stashed? Check for key presence rather than truthiness —
    # a completed run that returned 0 items stores ``[]`` which would
    # otherwise fall through and re-stash on every render. ``_start_scrape``
    # pops the key when a new run kicks off, so this guard correctly
    # re-populates from the new handle without repeated work.
    if results_tabs.K_RUN_ITEMS in st.session_state:
        return
    flat: list = []
    for r in results:
        flat.extend(r.items)
    results_tabs.stash_items(flat)


def render() -> None:
    ensure_defaults()
    st.title("News Scraping Dashboard")

    sources = load_sources()
    groupings = load_categorizers()
    app_settings = load_app_settings()

    if not sources:
        st.info(
            "No scraper sources configured yet. Head to **Settings → Scraper "
            "Configuration** to add your first portal.",
            icon="ℹ️",
        )
        return

    st.caption(f"{len(sources)} source(s) configured · {len(groupings)} categorizer grouping(s)")
    st.divider()

    # -- A. Time Range ---------------------------------------------------- #
    st.subheader("A. Time Range")
    tr = time_range.render(key_prefix="tr_main")
    span = time_range.months_span(tr)

    # -- B. Target Scrapers + page range --------------------------------- #
    st.subheader("B. Target Scrapers & Page Range")
    selections = source_selector.render(sources, months_span=span, key_prefix="ss_main")

    # -- C. Action & Progress -------------------------------------------- #
    st.subheader("C. Action & Progress")
    handle = st.session_state.get(K_JOB_HANDLE)
    is_running = handle is not None and handle.is_running()

    col1, col2 = st.columns([1, 3])
    with col1:
        start_clicked = st.button(
            "Start Scraping",
            type="primary",
            disabled=is_running,
            key="start_scrape_btn",
        )
    with col2:
        if is_running:
            st.caption("A scrape is in progress — watch the progress panel below.")
        elif handle is not None:
            st.caption("Last run finished. Starting a new run will reset progress.")

    if start_clicked and _start_scrape(selections, tr):
        st.rerun()

    progress_panel.render()

    # -- D. Results ------------------------------------------------------- #
    _collect_items_if_finished()
    st.subheader("D. Results")
    results_tabs.render(groupings, app_settings)
    # Export buttons sit below the tabs so they pick up whichever frame
    # the user has actively edited (the tabs render first and write the
    # edited frames to session state).
    export_panel.render(results_tabs.get_stashed_items(), groupings, app_settings)

    # -- E. Run history (Iter 11) ---------------------------------------- #
    st.subheader("E. Run history")
    run_history_panel.render()
