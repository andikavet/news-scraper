"""Settings Page — Categorization & Scraper configuration."""

from __future__ import annotations

import streamlit as st

from ui.components import categorizer_form, global_settings_form, scraper_form


def render() -> None:
    st.title("Settings")

    tab_scraper, tab_cat, tab_global = st.tabs(["Scrapers", "Categorization", "Global"])

    with tab_scraper:
        st.subheader("Scraper Configuration")
        scraper_form.render()

    with tab_cat:
        st.subheader("Categorization Configuration")
        categorizer_form.render()

    with tab_global:
        st.subheader("Global App Settings")
        global_settings_form.render()
