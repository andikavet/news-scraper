"""Integration tests for the Iter 8 fallback cascade inside the runner.

These go beyond :mod:`tests.test_fetch_orchestrator` by wiring the
orchestrator into :func:`run_url_params_source` end-to-end. They pin down
that:

1. ``RunStats.layer_usage`` correctly aggregates which layer served each
   page when the cascade is actively used.
2. ``PageFetched`` progress events carry ``layer_used`` so the UI can
   surface the cascade transparency.
3. When only Layer 1 is enabled, behaviour is identical to pre-Iter-8
   (regression guard on the back-compat alias).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from config import ScraperSelectors, ScrapeSource, SleepRange
from scraper.fetch_orchestrator import FetchOrchestrator
from scraper.layers.base import FetchResult, ScrapeError
from scraper.progress import PageFetched, ProgressBus
from scraper.runner import run_url_params_source

FIXTURES = Path(__file__).parent / "fixtures"
PAGE1 = (FIXTURES / "portalx_listing.html").read_text(encoding="utf-8")
PAGE2 = (FIXTURES / "portalx_page2.html").read_text(encoding="utf-8")


def _src(enabled: list[int]) -> ScrapeSource:
    return ScrapeSource(
        name="PortalX",
        pagination_type="url_params",
        url_template="https://portalx.test/news?page={page}",
        selectors=ScraperSelectors(
            container="li.article-item", title="h2", link="h2 a", date="span.date-time"
        ),
        sleep=SleepRange(min=0.0, max=0.0),
        max_retries=0,
        enabled_layers=enabled,  # type: ignore[arg-type]
    )


class _ScriptedLayer:
    """Like tests/test_fetch_orchestrator._StubLayer but keyed by URL."""

    def __init__(
        self,
        layer_number: int,
        name: str,
        parser_name: str,
        pages_by_url: dict[str, str] | None = None,
        fail_urls: set[str] | None = None,
    ) -> None:
        self.layer_number = layer_number
        self.name = name
        self.parser_name = parser_name
        self.pages_by_url = dict(pages_by_url or {})
        self.fail_urls = set(fail_urls or ())

    def fetch(self, url: str, timeout: float = 20.0) -> FetchResult:
        if url in self.fail_urls:
            raise ScrapeError(f"{self.name} blocked {url}")
        if url not in self.pages_by_url:
            raise ScrapeError(f"{self.name}: no page for {url}")
        return FetchResult(url=url, html=self.pages_by_url[url], status_code=200)


def _noop(_: float) -> None:  # pragma: no cover
    return None


REF = date(2026, 1, 15)
URL1 = "https://portalx.test/news?page=1"
URL2 = "https://portalx.test/news?page=2"


def test_runner_falls_back_to_layer2_when_layer1_blocks_every_page() -> None:
    """Adversarial: Layer 1 is 403 on every URL; Layer 2 serves every URL.

    Expected behaviour — layers work in parallel:
    - All pages still get scraped (items_in_range matches the no-fallback run).
    - ``layer_usage == {2: 2}`` because Layer 2 delivered both pages.
    - No page marked failed.
    """
    pages = {URL1: PAGE1, URL2: PAGE2}
    l1 = _ScriptedLayer(1, "l1", "bs4", fail_urls=set(pages.keys()))
    l2 = _ScriptedLayer(2, "l2", "selectolax", pages_by_url=pages)
    orch = FetchOrchestrator([l1, l2])

    result = run_url_params_source(
        _src([1, 2]),
        start_page=1,
        end_page=2,
        time_range_start=date(2026, 1, 1),
        orchestrator=orch,
        sleeper=_noop,
        reference_date=REF,
    )

    assert result.stats.pages_scanned == 2
    assert result.stats.pages_failed == 0
    assert result.stats.layer_usage == {2: 2}
    # Page 1 contributes 3 in-range items; Page 2 contributes '10 Jan 2026'
    # then hits a below-range date → early-stop is triggered on page 2.
    titles = [item.title for item in result.items]
    assert "Inflasi turun ke 2,3% bulan ini" in titles
    assert "Pembayaran utang BUMN lancar" in titles
    assert result.stats.early_stopped is True


def test_runner_mixes_layers_when_layer1_bounces_only_some_pages() -> None:
    """Layer 1 succeeds on page 1, fails on page 2 → Layer 2 picks up page 2.

    This is the canonical real-world case: rate-limiter kicks in mid-run.
    """
    l1 = _ScriptedLayer(1, "l1", "bs4", pages_by_url={URL1: PAGE1}, fail_urls={URL2})
    l2 = _ScriptedLayer(2, "l2", "selectolax", pages_by_url={URL2: PAGE2})
    orch = FetchOrchestrator([l1, l2])

    result = run_url_params_source(
        _src([1, 2]),
        start_page=1,
        end_page=2,
        time_range_start=date(2026, 1, 1),
        orchestrator=orch,
        sleeper=_noop,
        reference_date=REF,
    )
    assert result.stats.pages_failed == 0
    assert result.stats.layer_usage == {1: 1, 2: 1}


def test_runner_records_page_failure_when_every_layer_fails() -> None:
    """No layer has the URL → page marked failed, errors list populated, run continues."""
    l1 = _ScriptedLayer(1, "l1", "bs4", fail_urls={URL1, URL2})
    l2 = _ScriptedLayer(2, "l2", "selectolax", fail_urls={URL1, URL2})
    orch = FetchOrchestrator([l1, l2])

    result = run_url_params_source(
        _src([1, 2]),
        start_page=1,
        end_page=2,
        time_range_start=date(2026, 1, 1),
        orchestrator=orch,
        sleeper=_noop,
        reference_date=REF,
    )
    assert result.stats.pages_failed == 2
    assert len(result.stats.errors) == 2
    # Error message mentions both layers so the user can tell the cascade ran.
    assert "layer 1" in result.stats.errors[0]
    assert "layer 2" in result.stats.errors[0]
    # No pages were successfully fetched → layer_usage empty.
    assert result.stats.layer_usage == {}
    # No items collected.
    assert result.items == []


def test_pagefetched_events_carry_layer_used(capsys) -> None:  # type: ignore[no-untyped-def]
    """Each ``PageFetched`` event must tell the UI which layer delivered it."""
    pages = {URL1: PAGE1, URL2: PAGE2}
    l1 = _ScriptedLayer(1, "l1", "bs4", pages_by_url={URL1: PAGE1}, fail_urls={URL2})
    l2 = _ScriptedLayer(2, "l2", "selectolax", pages_by_url={URL2: PAGE2})
    orch = FetchOrchestrator([l1, l2])
    bus = ProgressBus()

    run_url_params_source(
        _src([1, 2]),
        start_page=1,
        end_page=2,
        time_range_start=date(2026, 1, 1),
        orchestrator=orch,
        sleeper=_noop,
        reference_date=REF,
        bus=bus,
    )

    events = bus.drain()
    fetched = [e for e in events if isinstance(e, PageFetched)]
    assert len(fetched) == 2
    # Event order follows page order, layer_used reflects which layer
    # actually served that page.
    assert [(e.page, e.layer_used) for e in fetched] == [(1, 1), (2, 2)]
    # pages used in the test
    assert pages.keys() == {URL1, URL2}  # sanity — not really an assertion on behaviour


def test_back_compat_fetcher_param_wraps_single_layer_no_fallback() -> None:
    """Passing ``fetcher=`` (legacy path) gives a 1-layer cascade — no fallback.

    Regression guard: the Iter 3 test ``_FakeFetcher`` calls still work
    unchanged via the back-compat alias.
    """
    # Fake only knows page 1; there is no fallback, so page 2 fails.
    fake = _ScriptedLayer(1, "fake", "bs4", pages_by_url={URL1: PAGE1}, fail_urls={URL2})

    result = run_url_params_source(
        _src([1]),
        start_page=1,
        end_page=2,
        time_range_start=date(2026, 1, 1),
        fetcher=fake,
        sleeper=_noop,
        reference_date=REF,
    )
    # Page 1 served by L1; page 2 has no fallback → failed.
    assert result.stats.layer_usage == {1: 1}
    assert result.stats.pages_failed == 1
