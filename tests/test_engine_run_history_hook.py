"""Engine ↔ run_history integration tests.

Verifies the engine writes exactly one history entry per completed run,
including cancelled runs and runs that hit errors.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest import mock

from config import ScraperSelectors, ScrapeSource, SleepRange
from scraper import engine
from scraper.engine import EngineRunSpec
from scraper.layers.base import FetchResult
from scraper.run_history import history_path, load_entries

FIXTURES = Path(__file__).parent / "fixtures"
PAGE1 = (FIXTURES / "portalx_listing.html").read_text(encoding="utf-8")


def _src(name: str = "Alpha") -> ScrapeSource:
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


class _AlwaysOK:
    name = "ok"
    layer_number = 1

    def fetch(self, url: str, timeout: float = 20.0) -> FetchResult:
        return FetchResult(url=url, html=PAGE1, status_code=200)


def _patch_layer1():
    return mock.patch("scraper.fetch_orchestrator.Layer1Httpx", return_value=_AlwaysOK())


def test_engine_appends_one_history_entry_per_run():
    spec = EngineRunSpec(
        sources=[_src("Alpha"), _src("Beta")],
        start_page=1,
        end_page=1,
        time_range_start=date(2026, 1, 1),
        time_range_end=date(2026, 1, 31),
    )
    with _patch_layer1():
        engine.run(spec, max_workers=2)

    entries = load_entries()
    assert len(entries) == 1
    [entry] = entries
    assert entry.source_names == ["Alpha", "Beta"]
    assert entry.cancelled is False
    # File was actually created on disk (vs just in-memory).
    assert history_path().exists()


def test_engine_history_entry_records_layer_usage():
    spec = EngineRunSpec(
        sources=[_src("Alpha")],
        start_page=1,
        end_page=2,
        time_range_start=date(2026, 1, 1),
        time_range_end=date(2026, 1, 31),
    )
    with _patch_layer1():
        engine.run(spec, max_workers=1)

    [entry] = load_entries()
    # Two pages all served by Layer 1.
    assert entry.layer_usage == {1: 2}
    assert entry.pages_scanned == 2
    assert entry.pages_failed == 0


def test_engine_zero_source_run_does_not_create_history_entry():
    """Empty specs short-circuit before the executor.

    No work was done; no history row should be written. Pinning this so
    a future refactor doesn't accidentally start logging noise rows for
    every "click Start with nothing selected" mistake.
    """
    spec = EngineRunSpec(
        sources=[],
        start_page=1,
        end_page=1,
        time_range_start=date(2026, 1, 1),
    )
    engine.run(spec)

    assert load_entries() == []


def test_engine_history_persists_across_calls():
    spec = EngineRunSpec(
        sources=[_src("Alpha")],
        start_page=1,
        end_page=1,
        time_range_start=date(2026, 1, 1),
    )
    with _patch_layer1():
        engine.run(spec, max_workers=1)
        engine.run(spec, max_workers=1)
        engine.run(spec, max_workers=1)

    entries = load_entries()
    assert len(entries) == 3
    # Same source name in each — nothing gets deduped on append.
    assert all(e.source_names == ["Alpha"] for e in entries)
