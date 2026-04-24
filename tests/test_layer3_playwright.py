"""End-to-end tests for ``Layer3Playwright``.

These exercise a real headless Chromium against a ``file://`` fixture that
injects its content via JS — so an HTML-only fetch (Layer 1) would see an
empty placeholder, while Layer 3 sees the rendered DOM.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config import ScraperSelectors
from scraper.layers.layer3_playwright import Layer3Playwright
from scraper.parsers import extract_items

FIXTURES = Path(__file__).parent / "fixtures"


pytestmark = pytest.mark.playwright


def _file_url(name: str) -> str:
    return (FIXTURES / name).absolute().as_uri()


def test_layer3_renders_spa_content():
    """A JS-injected article should be visible after Layer 3 fetch."""
    fetcher = Layer3Playwright()
    result = fetcher.fetch(_file_url("layer3_static.html"), timeout=15.0)

    assert "<main>" in result.html, "JS-injected <main> must be present"
    assert "Harga BBM dan pertanian naik" in result.html
    assert "Produksi pertanian stabil" in result.html

    selectors = ScraperSelectors(
        container="article.news-card",
        title="h3",
        link="h3 a",
        date="time",
    )
    hits = extract_items(result.html, selectors)
    titles = [h.title for h in hits]
    assert titles == [
        "Harga BBM dan pertanian naik",
        "Produksi pertanian stabil",
        "Konsumsi rumah tangga naik",
    ]
    assert all(h.link.startswith("https://example.test/") for h in hits)
