"""Smoke tests that catch the 'cannot import name X' class of mistakes.

If any UI component references a symbol that isn't re-exported from its module's
public surface, this test will fail at import time — not at Streamlit render time.
"""

from __future__ import annotations

import importlib


def test_can_import_app_module():
    importlib.import_module("app")


def test_can_import_settings_page():
    importlib.import_module("ui.pages.settings")


def test_can_import_main_dashboard_page():
    importlib.import_module("ui.pages.main_dashboard")


def test_can_import_each_settings_component():
    for mod in (
        "ui.components.scraper_form",
        "ui.components.categorizer_form",
        "ui.components.global_settings_form",
    ):
        importlib.import_module(mod)


def test_can_import_each_dashboard_component():
    for mod in (
        "ui.components.time_range",
        "ui.components.source_selector",
        "ui.components.progress_panel",
    ):
        importlib.import_module(mod)


def test_scrape_layer_is_exported_from_config():
    """Regression test: ScrapeLayer was missing from config/__init__.py and
    broke the Settings → Scrapers tab at runtime."""
    from config import ScrapeLayer  # noqa: F401


def test_streamlit_app_runs_without_exception():
    """Regression test: exercises the full ``app.py`` entry via Streamlit's
    AppTest harness so ``st.navigation`` / ``st.Page`` wiring errors (e.g.
    duplicate url_path inference) fail CI instead of silently hitting
    production."""
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file("app.py").run(timeout=15)
    assert not at.exception, f"App raised: {[str(e) for e in at.exception]}"
