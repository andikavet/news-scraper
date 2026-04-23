"""Streamlit entry point.

The entry file MUST stay thin: it only wires logging, loads config, and
dispatches to page render functions under ``ui/pages/``. Any real UI logic
belongs in ``ui/`` and any real scraping logic belongs in ``scraper/``.
"""

from __future__ import annotations

import streamlit as st

from config import load_app_settings
from ui.pages import main_dashboard, settings
from utils.logging import setup_logging


def _bootstrap() -> None:
    app_settings = load_app_settings()
    setup_logging(level=app_settings.log_level)


def main() -> None:
    st.set_page_config(
        page_title="News Scraper & Categorization",
        page_icon="📰",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _bootstrap()

    pages = {
        "App": [
            st.Page(
                main_dashboard.render,
                title="Dashboard",
                icon="📊",
                url_path="dashboard",
                default=True,
            ),
            st.Page(
                settings.render,
                title="Settings",
                icon="⚙️",
                url_path="settings",
            ),
        ],
    }
    nav = st.navigation(pages)
    nav.run()


if __name__ == "__main__":
    main()
