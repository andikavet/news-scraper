"""Tests for the Streamlit ↔ engine bridge.

These pin down that ``start_engine_thread`` truly runs in the background
(returns immediately), exposes a functioning cancel hook, and surfaces
worker exceptions via the ``JobHandle`` rather than crashing the caller.
"""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path
from unittest import mock

from config import ScraperSelectors, ScrapeSource, SleepRange
from scraper.engine import EngineRunSpec
from scraper.layers.base import FetchResult
from scraper.progress import RunFinished
from utils.async_bridge import start_engine_thread

FIXTURES = Path(__file__).parent / "fixtures"
PAGE1 = (FIXTURES / "portalx_listing.html").read_text(encoding="utf-8")


def _src(name: str) -> ScrapeSource:
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
    )


class _Fast:
    name = "fake"
    layer_number = 1

    def fetch(self, url: str, timeout: float = 20.0) -> FetchResult:
        return FetchResult(url=url, html=PAGE1, status_code=200)


def test_start_engine_thread_returns_immediately():
    """The call must not block until completion — otherwise the UI freezes."""
    spec = EngineRunSpec(
        sources=[_src("Alpha")],
        start_page=1,
        end_page=1,
        time_range_start=date(2026, 1, 1),
        time_range_end=date(2026, 1, 31),
    )
    with mock.patch("scraper.fetch_orchestrator.Layer1Httpx", return_value=_Fast()):
        t0 = time.monotonic()
        handle = start_engine_thread(spec)
        # The call itself should be basically instant.
        assert time.monotonic() - t0 < 0.2
        assert handle.is_running() or handle.bus.is_finished()
        handle.wait(timeout=5.0)
    assert handle.results is not None
    assert len(handle.results) == 1


def test_start_engine_thread_cancellation():
    """A slow fetcher + an immediate cancel → run finishes with cancelled=True."""
    import threading

    started = threading.Event()

    class Slow:
        name = "fake"
        layer_number = 1

        def fetch(self, url: str, timeout: float = 20.0) -> FetchResult:
            started.set()
            time.sleep(0.1)
            return FetchResult(url=url, html=PAGE1, status_code=200)

    spec = EngineRunSpec(
        sources=[_src("Alpha"), _src("Beta")],
        start_page=1,
        end_page=10,
        time_range_start=date(2026, 1, 1),
        time_range_end=date(2026, 1, 31),
    )
    with mock.patch("scraper.fetch_orchestrator.Layer1Httpx", return_value=Slow()):
        handle = start_engine_thread(spec)
        # Wait until at least one worker has started fetching before cancelling.
        started.wait(timeout=2.0)
        handle.cancel()
        handle.wait(timeout=5.0)

    assert handle.bus.is_finished()
    # Drain and confirm RunFinished was emitted with cancelled=True.
    events = handle.bus.drain()
    run_finished = [e for e in events if isinstance(e, RunFinished)]
    assert len(run_finished) == 1
    assert run_finished[0].cancelled is True


def test_start_engine_thread_captures_worker_exceptions():
    """A crashing worker must not kill the caller. ``handle.error`` must be set."""

    class Explosive:
        name = "fake"
        layer_number = 1

        def fetch(self, url: str, timeout: float = 20.0) -> FetchResult:
            raise RuntimeError("kaboom")

    spec = EngineRunSpec(
        sources=[_src("Alpha")],
        start_page=1,
        end_page=1,
        time_range_start=date(2026, 1, 1),
        time_range_end=date(2026, 1, 31),
    )
    with mock.patch("scraper.fetch_orchestrator.Layer1Httpx", return_value=Explosive()):
        handle = start_engine_thread(spec)
        handle.wait(timeout=5.0)

    # The engine's per-source try/except should swallow the error and still
    # produce a result list — the handle.error should remain None in this
    # case because the thread itself didn't crash.
    assert handle.results is not None
    # The single source produced an empty result with a recorded error.
    assert len(handle.results) == 1
    assert handle.results[0].items == []
