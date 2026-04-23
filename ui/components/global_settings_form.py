"""Global app-settings form on the Settings page.

Edits the AppSettings singleton (overall_exclude_tokens, sleep defaults,
max_retries default, log level).
"""

from __future__ import annotations

import streamlit as st

from config import AppSettings, load_app_settings, save_app_settings


def render() -> None:
    settings = load_app_settings()
    with st.form("global_settings_form"):
        excludes_raw = st.text_area(
            "Overall exclude tokens (comma-separated)",
            value=", ".join(settings.overall_exclude_tokens),
            help=(
                "Any article whose lowercased title contains one of these tokens is "
                "discarded before categorization."
            ),
        )
        c1, c2 = st.columns(2)
        with c1:
            default_min = st.number_input(
                "Default min sleep (sec)",
                min_value=0.0,
                value=float(settings.default_min_sleep),
                step=0.5,
            )
            default_retries = st.number_input(
                "Default max retries",
                min_value=0,
                value=int(settings.default_max_retries),
                step=1,
            )
        with c2:
            default_max = st.number_input(
                "Default max sleep (sec)",
                min_value=0.0,
                value=float(settings.default_max_sleep),
                step=0.5,
            )
            log_level = st.selectbox(
                "Log level",
                options=("DEBUG", "INFO", "WARNING", "ERROR"),
                index=("DEBUG", "INFO", "WARNING", "ERROR").index(settings.log_level),
            )

        save = st.form_submit_button("Save global settings", type="primary")

    if save:
        tokens = [t.strip() for t in excludes_raw.split(",") if t.strip()]
        if default_max < default_min:
            st.error("default_max_sleep must be >= default_min_sleep.")
            return
        save_app_settings(
            AppSettings(
                overall_exclude_tokens=tokens,
                default_min_sleep=float(default_min),
                default_max_sleep=float(default_max),
                default_max_retries=int(default_retries),
                log_level=log_level,
            )
        )
        st.success("Saved.")
        st.rerun()


__all__ = ["render"]
