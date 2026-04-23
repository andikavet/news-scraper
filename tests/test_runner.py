"""Tests for the per-source scraping loop.

Uses a fake fetcher that serves canned HTML per page so the runner can be
driven deterministically with no network and no real sleeps.
"""

from __future__ import annotations

import random
from datetime import date
from pathlib import Path

import pytest

from config import ScraperSelectors, ScrapeSource, SleepRange
from scraper.layers.base import FetchResult, ScrapeError
from scraper.runner import run_layer1_source

FIXTURES = Path(__file__).parent / "fixtures"
PAGE1 = (FIXTURES / "portalx_listing.html").read_text(encoding="utf-8")
PAGE2 = (FIXTURES / "portalx_page2.html").read_text(encoding="utf-8")


def _source(max_retries: int = 0) -> ScrapeSource:
    return ScrapeSource(
        name="PortalX",
        pagination_type="url_params",
        url_template="https://portalx.test/news?page={page}",
        selectors=ScraperSelectors(
            container="li.article-item",
            title="h2",
            link="h2 a",
            date="span.date-time",
        ),
        sleep=SleepRange(min=0.0, max=0.0),
        max_retries=max_retries,
        enabled_layers=[1],
    )


class _FakeFetcher:
    """Serves ``pages[url]`` → HTML; raises ``ScrapeError`` if the URL is not mapped."""

    name = "fake"
    layer_number = 1

    def __init__(
        self,
        pages: dict[str, str],
        fail_urls: dict[str, int] | None = None,
    ) -> None:
        self.pages = pages
        self.fail_urls = dict(fail_urls or {})
        self.calls: list[str] = []

    def fetch(self, url: str, timeout: float = 20.0) -> FetchResult:
        self.calls.append(url)
        if url in self.fail_urls and self.fail_urls[url] > 0:
            self.fail_urls[url] -= 1
            raise ScrapeError(f"simulated transient failure on {url}")
        if url not in self.pages:
            raise ScrapeError(f"no fixture for {url}")
        return FetchResult(url=url, html=self.pages[url], status_code=200)


def _noop_sleep(_seconds: float) -> None:  # pragma: no cover - trivial
    return None


REF = date(2026, 1, 15)


def test_runner_collects_in_range_items():
    src = _source()
    fetcher = _FakeFetcher({"https://portalx.test/news?page=1": PAGE1})
    result = run_layer1_source(
        src,
        start_page=1,
        end_page=1,
        time_range_start=date(2026, 1, 1),
        time_range_end=date(2026, 1, 31),
        fetcher=fetcher,
        sleeper=_noop_sleep,
        reference_date=REF,
    )
    titles = [i.title for i in result.items]
    assert titles == [
        "Inflasi turun ke 2,3% bulan ini",
        "Ekspor non-migas naik 8%",
        "APBN 2026 disahkan DPR",
    ]
    assert result.stats.pages_scanned == 1
    assert result.stats.items_scanned == 3  # sponsor row has no title+link, skipped before we count
    assert result.stats.items_in_range == 3
    assert result.stats.early_stopped is False


def test_runner_resolves_relative_links_as_provided():
    """Runner does not rewrite links; it stores them as selectors returned them."""
    src = _source()
    fetcher = _FakeFetcher({"https://portalx.test/news?page=1": PAGE1})
    result = run_layer1_source(
        src,
        1,
        1,
        date(2026, 1, 1),
        fetcher=fetcher,
        sleeper=_noop_sleep,
        reference_date=REF,
    )
    links = [i.link for i in result.items]
    assert "/berita/inflasi-turun" in links
    assert "https://portalx.test/berita/ekspor-naik" in links


def test_runner_early_stops_when_date_below_range():
    """Page 2 includes '28 Des 2025' and '15 Des 2025' — both older than the
    range start (1 Jan 2026). Early-stop must fire after page 2 and the
    runner must NOT touch page 3 even if end_page=3.
    """
    src = _source()
    fetcher = _FakeFetcher(
        {
            "https://portalx.test/news?page=1": PAGE1,
            "https://portalx.test/news?page=2": PAGE2,
        }
    )
    result = run_layer1_source(
        src,
        start_page=1,
        end_page=3,
        time_range_start=date(2026, 1, 1),
        time_range_end=None,
        fetcher=fetcher,
        sleeper=_noop_sleep,
        reference_date=REF,
    )
    # Page 3 must never be requested.
    assert fetcher.calls == [
        "https://portalx.test/news?page=1",
        "https://portalx.test/news?page=2",
    ]
    assert result.stats.early_stopped is True
    assert result.stats.pages_scanned == 2
    # Page 2's '10 Jan 2026' is in range; '28 Des 2025' and '15 Des 2025' are not.
    titles = [i.title for i in result.items]
    assert "Pembayaran utang BUMN lancar" in titles
    assert "Tambang batu bara tutup 2025" not in titles
    assert "Harga beras stabil" not in titles
    assert result.stats.items_out_of_range == 2


def test_runner_retries_transient_failures_then_succeeds():
    src = _source(max_retries=2)
    fetcher = _FakeFetcher(
        pages={"https://portalx.test/news?page=1": PAGE1},
        fail_urls={"https://portalx.test/news?page=1": 1},  # fail once, then succeed
    )
    result = run_layer1_source(
        src,
        1,
        1,
        date(2026, 1, 1),
        fetcher=fetcher,
        sleeper=_noop_sleep,
        reference_date=REF,
    )
    assert len(fetcher.calls) == 2  # 1 failure + 1 success
    assert result.stats.pages_failed == 0
    assert result.stats.items_in_range == 3


def test_runner_gives_up_after_max_retries_and_continues():
    """Failing page must be recorded but the loop must still try the next page."""
    src = _source(max_retries=1)
    fetcher = _FakeFetcher(
        pages={
            "https://portalx.test/news?page=1": PAGE1,
            "https://portalx.test/news?page=2": PAGE2,
        },
        fail_urls={"https://portalx.test/news?page=1": 99},  # always fails
    )
    result = run_layer1_source(
        src,
        start_page=1,
        end_page=2,
        time_range_start=date(2026, 1, 1),
        fetcher=fetcher,
        sleeper=_noop_sleep,
        reference_date=REF,
    )
    assert result.stats.pages_scanned == 2
    assert result.stats.pages_failed == 1
    assert len(result.stats.errors) == 1
    # Page 2 still runs and contributes '10 Jan 2026' → triggers early stop on that page.
    titles = [i.title for i in result.items]
    assert "Pembayaran utang BUMN lancar" in titles
    assert result.stats.early_stopped is True


def test_runner_sleeps_between_pages_but_not_after_last():
    src = _source()
    src.sleep.min = 1.0
    src.sleep.max = 1.0
    fetcher = _FakeFetcher(
        {
            "https://portalx.test/news?page=1": PAGE1,
            "https://portalx.test/news?page=2": PAGE2,
        }
    )
    sleeps: list[float] = []
    run_layer1_source(
        src,
        1,
        2,
        date(2026, 1, 1),
        fetcher=fetcher,
        sleeper=lambda s: sleeps.append(s),
        rng=random.Random(0),
        reference_date=REF,
    )
    # Exactly one inter-page sleep (after page 1). No sleep after page 2.
    # (If early-stop fires we may also get zero sleeps — this source does
    # early-stop on page 2, so no post-page-2 sleep either.)
    assert sleeps == [1.0]


def test_runner_rejects_invalid_page_range():
    src = _source()
    with pytest.raises(ValueError):
        run_layer1_source(
            src,
            start_page=0,
            end_page=1,
            time_range_start=date(2026, 1, 1),
            fetcher=_FakeFetcher({}),
            sleeper=_noop_sleep,
            reference_date=REF,
        )
    with pytest.raises(ValueError):
        run_layer1_source(
            src,
            start_page=3,
            end_page=2,
            time_range_start=date(2026, 1, 1),
            fetcher=_FakeFetcher({}),
            sleeper=_noop_sleep,
            reference_date=REF,
        )
