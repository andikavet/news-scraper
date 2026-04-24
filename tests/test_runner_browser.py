"""Integration tests for :func:`scraper.runner.run_browser_source`.

Drives the real browser via file:// fixtures for both infinite_scroll and
click_next, and verifies:

- Dedup by link so infinite-scroll cumulative snapshots are not double-counted.
- Per-page ``PageFetched`` event deltas reflect *new* items only.
- Early-stop when a parsed date falls below the selected time range.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from config import ScraperSelectors, ScrapeSource
from scraper.progress import PageFetched, ProgressBus, SourceStarted
from scraper.runner import run_browser_source

FIXTURES = Path(__file__).parent / "fixtures"

pytestmark = pytest.mark.playwright


def _file_url(name: str) -> str:
    return (FIXTURES / name).absolute().as_uri()


def _infinite_scroll_source() -> ScrapeSource:
    return ScrapeSource(
        name="ScrollX",
        pagination_type="infinite_scroll",
        url_template=_file_url("infinite_scroll.html"),
        selectors=ScraperSelectors(
            container="article.news-card",
            title="h3",
            link="h3 a",
            date="time",
        ),
        scrolls_per_page=1,
        enabled_layers=[3],
    )


def _click_next_source() -> ScrapeSource:
    return ScrapeSource(
        name="ClickX",
        pagination_type="click_next",
        url_template=_file_url("click_next.html"),
        selectors=ScraperSelectors(
            container="article.news-card",
            title="h3",
            link="h3 a",
            date="time",
            next_button="#next",
        ),
        enabled_layers=[3],
    )


REFERENCE = date(2026, 4, 30)


def test_infinite_scroll_run_dedupes_and_emits_per_page_deltas():
    bus = ProgressBus()
    result = run_browser_source(
        _infinite_scroll_source(),
        start_page=1,
        end_page=4,
        time_range_start=date(2026, 4, 1),
        time_range_end=date(2026, 4, 30),
        reference_date=REFERENCE,
        bus=bus,
    )

    # 8 unique articles in the fixture, all within the April 2026 range.
    titles = [i.title for i in result.items]
    assert len(titles) == 8
    assert titles[0] == "Harga BBM dan pertanian naik"
    assert titles[-1] == "APBN 2026 disahkan"
    assert result.stats.items_in_range == 8
    assert result.stats.items_scanned == 8
    assert result.stats.pages_scanned == 4

    events = bus.drain()
    assert any(isinstance(e, SourceStarted) for e in events)
    page_fetched = [e for e in events if isinstance(e, PageFetched)]
    # Page 1 contributes 2 new; pages 2-4 contribute 2 new each (cumulative
    # snapshots dedupe correctly).
    assert [e.items_in_range for e in page_fetched] == [2, 2, 2, 2]


def test_click_next_run_stops_when_button_disappears():
    bus = ProgressBus()
    result = run_browser_source(
        _click_next_source(),
        start_page=1,
        end_page=10,  # fixture only has 3 pages; button disables itself
        time_range_start=date(2026, 4, 1),
        time_range_end=date(2026, 4, 30),
        reference_date=REFERENCE,
        bus=bus,
    )

    assert result.stats.pages_scanned == 3
    assert result.stats.items_in_range == 6
    titles = [i.title for i in result.items]
    assert titles[0].startswith("Page 1 item")
    assert titles[-1].startswith("Page 3 item")


def test_infinite_scroll_early_stops_when_date_below_range():
    bus = ProgressBus()
    # Time-range start on 20 Apr 2026 → articles dated 19 Apr and earlier
    # must trigger early-stop once encountered. The fixture's 4th article
    # (page 2 delta) is dated 19 Apr, so early-stop fires on page 2.
    result = run_browser_source(
        _infinite_scroll_source(),
        start_page=1,
        end_page=4,
        time_range_start=date(2026, 4, 20),
        time_range_end=None,
        reference_date=REFERENCE,
        bus=bus,
    )

    assert result.stats.early_stopped is True
    assert result.stats.pages_scanned == 2  # stopped after page 2
    # Only items on/after 20 Apr kept: 3 titles (22, 21, 20 Apr).
    assert [i.title for i in result.items] == [
        "Harga BBM dan pertanian naik",
        "Produksi pertanian stabil",
        "Konsumsi rumah tangga naik",
    ]
