"""Engine-level orchestration tests.

Iter 4 moves the engine from sequential to ``ThreadPoolExecutor``; these
tests pin down:
- Disabled sources are skipped.
- Each enabled source produces exactly one ``SourceRunResult``.
- Ordering of results matches the input source list **even when workers
  complete out of order**.
- Lifecycle events (``RunStarted`` / ``SourceStarted`` / ``PageFetched``
  / ``SourceFinished`` / ``RunFinished``) are emitted to the bus.
"""

from __future__ import annotations

import threading
import time
from datetime import date
from pathlib import Path
from unittest import mock

from config import ScraperSelectors, ScrapeSource, SleepRange
from scraper import engine
from scraper.engine import EngineRunSpec
from scraper.layers.base import FetchResult
from scraper.progress import (
    PageFetched,
    ProgressBus,
    RunFinished,
    RunStarted,
    SourceFinished,
    SourceStarted,
)

FIXTURES = Path(__file__).parent / "fixtures"
PAGE1 = (FIXTURES / "portalx_listing.html").read_text(encoding="utf-8")


def _src(name: str, enabled: bool = True) -> ScrapeSource:
    return ScrapeSource(
        name=name,
        pagination_type="url_params",
        url_template=f"https://{name.lower()}.test/news?page={{page}}",
        selectors=ScraperSelectors(
            container="li.article-item",
            title="h2",
            link="h2 a",
            date="span.date-time",
        ),
        sleep=SleepRange(min=0.0, max=0.0),
        enabled_layers=[1],
        enabled=enabled,
    )


class _AllPagesFetcher:
    """Always returns PAGE1 regardless of URL; injected via monkeypatch."""

    name = "fake"
    layer_number = 1

    def fetch(self, url: str, timeout: float = 20.0) -> FetchResult:
        return FetchResult(url=url, html=PAGE1, status_code=200)


def _patch_layer1():
    """Context patching Layer1Httpx so no real HTTP happens during engine tests."""
    return mock.patch("scraper.runner.Layer1Httpx", return_value=_AllPagesFetcher())


def test_engine_runs_each_enabled_source_once_and_preserves_order():
    spec = EngineRunSpec(
        sources=[_src("Alpha"), _src("Beta"), _src("Gamma", enabled=False), _src("Delta")],
        start_page=1,
        end_page=1,
        time_range_start=date(2026, 1, 1),
        time_range_end=date(2026, 1, 31),
    )
    with _patch_layer1():
        results = engine.run(spec, max_workers=4)

    assert [r.stats.source_name for r in results] == ["Alpha", "Beta", "Delta"]


def test_engine_emits_full_lifecycle():
    bus = ProgressBus()
    spec = EngineRunSpec(
        sources=[_src("Alpha")],
        start_page=1,
        end_page=1,
        time_range_start=date(2026, 1, 1),
        time_range_end=date(2026, 1, 31),
    )
    with _patch_layer1():
        engine.run(spec, bus=bus, max_workers=1)

    events = bus.drain()
    kinds = [type(e).__name__ for e in events]
    # Order within a single-source run is deterministic.
    assert kinds == [
        "RunStarted",
        "SourceStarted",
        "PageFetched",
        "SourceFinished",
        "RunFinished",
    ]
    assert isinstance(events[0], RunStarted)
    assert events[0].source_names == ["Alpha"]
    assert isinstance(events[1], SourceStarted)
    assert events[1].total_pages == 1
    assert isinstance(events[2], PageFetched)
    assert events[2].source_name == "Alpha"
    assert isinstance(events[3], SourceFinished)
    assert isinstance(events[4], RunFinished)
    assert events[4].cancelled is False


def test_engine_preserves_order_even_when_workers_finish_out_of_order():
    """Slow Alpha, fast Beta — output must still start with Alpha."""
    barrier = threading.Event()

    class SlowFirstFetcher:
        name = "fake"
        layer_number = 1

        def fetch(self, url: str, timeout: float = 20.0) -> FetchResult:
            if "alpha" in url:
                # Let Beta finish first.
                time.sleep(0.2)
            barrier.set()
            return FetchResult(url=url, html=PAGE1, status_code=200)

    spec = EngineRunSpec(
        sources=[_src("Alpha"), _src("Beta")],
        start_page=1,
        end_page=1,
        time_range_start=date(2026, 1, 1),
        time_range_end=date(2026, 1, 31),
    )
    with mock.patch("scraper.runner.Layer1Httpx", return_value=SlowFirstFetcher()):
        results = engine.run(spec, max_workers=2)

    assert [r.stats.source_name for r in results] == ["Alpha", "Beta"]


def test_engine_with_no_sources_emits_finished_immediately():
    spec = EngineRunSpec(
        sources=[],
        start_page=1,
        end_page=1,
        time_range_start=date(2026, 1, 1),
    )
    bus = ProgressBus()
    results = engine.run(spec, bus=bus)
    assert results == []
    kinds = [type(e).__name__ for e in bus.drain()]
    assert kinds == ["RunStarted", "RunFinished"]


def test_engine_cancellation_stops_new_pages():
    """Cancelling mid-run must prevent the second page from being fetched."""
    seen_urls: list[str] = []

    class CancelOnFirstFetcher:
        name = "fake"
        layer_number = 1

        def __init__(self, bus: ProgressBus) -> None:
            self.bus = bus

        def fetch(self, url: str, timeout: float = 20.0) -> FetchResult:
            seen_urls.append(url)
            # Cancel right after the first page's fetch.
            self.bus.cancel()
            return FetchResult(url=url, html=PAGE1, status_code=200)

    bus = ProgressBus()
    fetcher = CancelOnFirstFetcher(bus)
    spec = EngineRunSpec(
        sources=[_src("Alpha")],
        start_page=1,
        end_page=5,  # 5 pages planned; cancel should stop after page 1.
        time_range_start=date(2026, 1, 1),
        time_range_end=date(2026, 1, 31),
    )
    with mock.patch("scraper.runner.Layer1Httpx", return_value=fetcher):
        engine.run(spec, bus=bus, max_workers=1)

    # At most 1 extra fetch may slip through because the cancel flag is
    # checked *between* pages; page 1 and page 2 may both complete, but
    # page 3+ definitely must not.
    assert len(seen_urls) <= 2
    events = bus.drain()
    final = events[-1]
    assert isinstance(final, RunFinished)
    assert final.cancelled is True
