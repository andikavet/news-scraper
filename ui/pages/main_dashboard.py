"""Main Page — Scraping Dashboard.

Iteration 1 scaffold: renders placeholders for each PRD section so we can see
the page routing working end-to-end. Real behaviour lands in later iterations.
"""

from __future__ import annotations

import streamlit as st

from config import load_categorizers, load_sources
from ui.state import ensure_defaults


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
    else:
        st.caption(
            f"{len(sources)} source(s) configured · {len(groupings)} categorizer grouping(s)"
        )

    st.divider()

    st.subheader("A. Time Range")
    st.caption("Quick selectors and manual Start/End month+year dropdowns — wired in Iteration 4.")

    st.subheader("B. Target Scrapers & Page Range")
    st.caption("Checkbox list + auto-calculated End Page — wired in Iteration 4.")

    st.subheader("C. Action & Progress")
    st.caption("Start Scraping button, overall + per-source async progress bars — Iteration 4.")

    st.subheader("D. Results")
    st.caption(
        "Editable tables per grouping, pivot tables with full category reindex, "
        "and the raw-data read-only dataframe — Iterations 5 & 6."
    )
