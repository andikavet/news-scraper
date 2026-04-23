"""The 'Test Selector' tool wired for the Settings page.

Runs a single Layer 1 fetch against one URL and applies the user-provided
selectors. Returns a ``TestSelectorResult`` that the UI renders as either a
preview table or an error banner.

This deliberately stays on Layer 1 only — higher layers spin up Playwright,
which would be a terrible UX for a "click and see what you got" button.
Iteration 7 can add a "Test Selector (Playwright)" toggle if needed.
"""

from __future__ import annotations

from config import ScraperSelectors
from scraper.layers.base import ScrapeError
from scraper.layers.layer1_httpx import Layer1Httpx
from scraper.models import TestSelectorResult
from scraper.parsers import extract_items


def run_selector_test(url: str, selectors: ScraperSelectors) -> TestSelectorResult:
    """Fetch ``url`` once via Layer 1 and return whatever the selectors found."""
    layer = Layer1Httpx()
    try:
        fetched = layer.fetch(url)
    except ScrapeError as e:
        return TestSelectorResult(
            ok=False,
            url=url,
            status_code=None,
            layer=layer.name,
            error=str(e),
        )

    items = extract_items(fetched.html, selectors)
    return TestSelectorResult(
        ok=True,
        url=fetched.url,
        status_code=fetched.status_code,
        layer=layer.name,
        items=items,
    )


__all__ = ["run_selector_test"]
