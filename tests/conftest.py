"""Shared pytest fixtures / markers.

Declares the ``playwright`` marker used to opt-in tests that require a real
Chromium binary. The Playwright browser is installed in CI via a dedicated
step (see ``.github/workflows/ci.yml``); locally, developers can run
``playwright install chromium`` once.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


def _chromium_binary_available() -> bool:
    """Best-effort check for a usable Chromium build.

    Playwright stores downloaded browsers under ``~/.cache/ms-playwright`` on
    Linux. If the directory is missing, skip Playwright-dependent tests with
    a useful message rather than raising a noisy Playwright error.
    """
    override = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override))
    candidates.append(Path.home() / ".cache" / "ms-playwright")
    for base in candidates:
        if not base.exists():
            continue
        if any(base.glob("chromium-*")) or any(base.glob("chromium_headless_shell-*")):
            return True
    return False


def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    if _chromium_binary_available():
        return
    skip_playwright = pytest.mark.skip(
        reason="Playwright chromium binary not installed; run `playwright install chromium`."
    )
    for item in items:
        if "playwright" in item.keywords:
            item.add_marker(skip_playwright)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "playwright: marks tests that require a real Playwright chromium install"
    )


@pytest.fixture(autouse=True)
def _isolate_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect the config layer at a per-test tmp dir.

    Iter 11 added :mod:`scraper.run_history` which the engine writes to on
    every completed run. Without isolation, every engine-touching test in
    the suite would silently scribble into the developer's real
    ``config/run_history.json``. Routing the config dir through a tmp path
    keeps tests hermetic.

    Tests that care about config files (e.g. ``test_config_store``) set
    their own ``NEWS_SCRAPER_CONFIG_DIR`` via monkeypatch; this fixture's
    setting is shadowed by the inner monkeypatch and restored when that
    test ends.
    """
    monkeypatch.setenv("NEWS_SCRAPER_CONFIG_DIR", str(tmp_path))
    yield tmp_path
