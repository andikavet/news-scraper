"""Settings Page — Categorization & Scraper configuration.

Iteration 1 scaffold: tabbed layout with placeholders so navigation is live and
routing is verified. CRUD forms + CSV upload + Test Selector land in Iteration 2.
"""

from __future__ import annotations

import streamlit as st

from config import load_app_settings, load_categorizers, load_sources


def render() -> None:
    st.title("Settings")

    tab_cat, tab_scraper, tab_global = st.tabs(["Categorization", "Scrapers", "Global"])

    with tab_cat:
        st.subheader("Categorization Configuration")
        groupings = load_categorizers()
        st.caption(
            f"{len(groupings)} grouping(s) configured. "
            "Add/edit groupings and upload CSV rule tables in Iteration 2."
        )

    with tab_scraper:
        st.subheader("Scraper Configuration")
        sources = load_sources()
        st.caption(
            f"{len(sources)} source(s) configured. "
            "Create/edit sources and run the 'Test Selector' tool in Iteration 2."
        )

    with tab_global:
        st.subheader("Global App Settings")
        settings = load_app_settings()
        st.json(settings.model_dump(), expanded=False)
        st.caption("Overall Exclude Tokens and defaults. Editable form in Iteration 2.")
