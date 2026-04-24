"""Integration tests for :mod:`scraper.playwright_session`.

Exercise the real browser against deterministic file:// fixtures so we verify
both strategies end to end without a network dependency.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config import ScraperSelectors
from scraper.parsers import extract_items
from scraper.playwright_session import (
    BrowserSessionError,
    browser_page,
    iter_click_next_pages,
    iter_infinite_scroll_pages,
)

FIXTURES = Path(__file__).parent / "fixtures"

pytestmark = pytest.mark.playwright


def _file_url(name: str) -> str:
    return (FIXTURES / name).absolute().as_uri()


NEWS_SELECTORS = ScraperSelectors(
    container="article.news-card",
    title="h3",
    link="h3 a",
    date="time",
    next_button="#next",
)


# --------------------------------------------------------------------------- #
# infinite_scroll
# --------------------------------------------------------------------------- #


def test_infinite_scroll_yields_cumulative_snapshots():
    """Each yielded page must have >= the previous page's items."""
    titles_per_page: list[list[str]] = []
    with browser_page() as page:
        for snap in iter_infinite_scroll_pages(
            page,
            url=_file_url("infinite_scroll.html"),
            start_page=1,
            end_page=4,
            scrolls_per_page=1,
        ):
            titles_per_page.append([h.title for h in extract_items(snap.html, NEWS_SELECTORS)])

    # Page 1 (no scrolls yet) has the 2 server-rendered articles.
    assert titles_per_page[0] == [
        "Harga BBM dan pertanian naik",
        "Produksi pertanian stabil",
    ]
    # Pages 2-4 each reveal one more batch of 2 articles.
    assert len(titles_per_page[1]) == 4
    assert len(titles_per_page[2]) == 6
    assert len(titles_per_page[3]) == 8
    # Last page has the whole feed in order.
    assert titles_per_page[-1][-1] == "APBN 2026 disahkan"


def test_infinite_scroll_stops_on_should_stop():
    """``should_stop`` is polled between pages; iterator exits cleanly."""
    snapshots: list = []

    def stop_after_two_pages() -> bool:
        return len(snapshots) >= 2

    with browser_page() as page:
        for snap in iter_infinite_scroll_pages(
            page,
            url=_file_url("infinite_scroll.html"),
            start_page=1,
            end_page=10,
            scrolls_per_page=1,
            should_stop=stop_after_two_pages,
        ):
            snapshots.append(snap)

    assert [s.page for s in snapshots] == [1, 2]


# --------------------------------------------------------------------------- #
# click_next
# --------------------------------------------------------------------------- #


def test_click_next_yields_three_pages_in_order():
    titles_per_page: list[list[str]] = []
    with browser_page() as page:
        for snap in iter_click_next_pages(
            page,
            url=_file_url("click_next.html"),
            next_button_selector="#next",
            start_page=1,
            end_page=5,  # on purpose: site only has 3 pages
        ):
            titles_per_page.append([h.title for h in extract_items(snap.html, NEWS_SELECTORS)])

    assert len(titles_per_page) == 3
    assert all(
        titles[0].startswith(f"Page {i + 1} item") for i, titles in enumerate(titles_per_page)
    )
    # Each page has exactly 2 articles (no cumulative stacking).
    assert all(len(t) == 2 for t in titles_per_page)


def test_click_next_requires_next_button_selector():
    with browser_page() as page, pytest.raises(BrowserSessionError):
        list(
            iter_click_next_pages(
                page,
                url=_file_url("click_next.html"),
                next_button_selector=None,
                start_page=1,
                end_page=2,
            )
        )
