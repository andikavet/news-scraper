"""Main Page — Scraping Dashboard.

Iteration 4 wires the time-range picker, source selector, and live
progress panel together. Clicking "Start Scraping" kicks off the engine
on a background thread (via ``utils.async_bridge.start_engine_thread``)
so the UI stays responsive; the progress panel polls the bus and
auto-refreshes via an ``st.fragment``.

Results surfacing (the "D. Results" section) still shows placeholders —
that's Iterations 5 & 6.
"""

from __future__ import annotations

import streamlit as st

from config import load_categorizers, load_sources
from scraper.engine import EngineRunSpec
from ui.components import progress_panel, source_selector, time_range
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

    # All selections share the same [start_page, end_page] envelope on the
    # engine, but per-source overrides would diverge — so we take the min
    # start_page and max end_page across selected sources. This is a
    # reasonable first-cut; Iter 9 lets each source have its own bounds.
    start_page = min(s.start_page for s in picked)
    end_page = max(s.end_page for s in picked)
    if end_page < start_page:
        st.error("End page is before start page — nothing to do.")
        return False

    spec = EngineRunSpec(
        sources=[s.source for s in picked],
        start_page=start_page,
        end_page=end_page,
        time_range_start=tr.start,
        time_range_end=tr.end,
    )
    progress_panel.reset_snapshot()
    st.session_state[K_JOB_HANDLE] = start_engine_thread(spec)
    return True


def render() -> None:
    ensure_defaults()
    st.title("News Scraping Dashboard")

    sources = load_sources()
    groupings = load_categorizers()

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

    # -- D. Results (placeholder — Iter 5 & 6) --------------------------- #
    st.subheader("D. Results")
    st.caption(
        "Editable tables per grouping, pivot tables with full category reindex, "
        "and the raw-data read-only dataframe — Iterations 5 & 6."
    )
