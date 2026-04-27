"""Global app-settings form on the Settings page.

Edits the AppSettings singleton (overall_exclude_tokens, sleep defaults,
max_retries default, log level).

Iter 12: every save action surfaces an inline ``st.success`` /
``st.error`` /``st.warning`` banner. The success banner stages in session
state so it survives the ``st.rerun()`` that fires immediately after a
successful save.
"""

from __future__ import annotations

import streamlit as st

from config import AppSettings, load_app_settings, save_app_settings

_STATUS_KEY = "global_settings_status"


def _flash(level: str, message: str) -> None:
    st.session_state[_STATUS_KEY] = (level, message)


def _consume_status() -> None:
    pending = st.session_state.pop(_STATUS_KEY, None)
    if pending is None:
        return
    level, message = pending
    if level == "success":
        st.success(message)
    elif level == "error":
        st.error(message)
    elif level == "warning":
        st.warning(message)
    else:
        st.info(message)


def render() -> None:
    _consume_status()
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
        _flash(
            "success",
            f"Saved global settings ({len(tokens)} exclude token(s); log level={log_level}).",
        )
        st.rerun()


__all__ = ["render"]
