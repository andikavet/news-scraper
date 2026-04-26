"""Pin Iter 10's per-source ``end_page`` envelope.

The Iter 7 nit was: two sources with auto-calculated ``end_page=3`` and
``end_page=10`` respectively shared a ``/10`` denominator on the
progress bar because the engine took the max envelope across the
selected sources. Iter 10 lets the UI pass each source its own
``(start_page, end_page)`` via ``EngineRunSpec.per_source_pages``; this
file proves the per-source bounds actually flow through to the runner
calls and the ``RunStarted`` total page count.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest import mock

from config import ScraperSelectors, ScrapeSource, SleepRange
from scraper import engine
from scraper.engine import EngineRunSpec
from scraper.layers.base import FetchResult
from scraper.progress import ProgressBus, RunStarted

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


class _AllPagesFetcher:
    name = "fake"
    layer_number = 1

    def fetch(self, url: str, timeout: float = 20.0) -> FetchResult:
        return FetchResult(url=url, html=PAGE1, status_code=200)


def _patch_layer1():
    return mock.patch("scraper.fetch_orchestrator.Layer1Httpx", return_value=_AllPagesFetcher())


def test_bounds_for_returns_per_source_when_present_else_default() -> None:
    spec = EngineRunSpec(
        sources=[_src("Alpha"), _src("Beta")],
        start_page=1,
        end_page=10,  # default upper bound
        time_range_start=date(2026, 1, 1),
        per_source_pages={"Alpha": (1, 3)},
    )
    # Alpha gets the override, Beta falls back to default.
    assert spec.bounds_for("Alpha") == (1, 3)
    assert spec.bounds_for("Beta") == (1, 10)


def test_run_started_total_pages_sums_per_source_bounds_not_max() -> None:
    """Two sources at /3 and /10 → total=13, not 20.

    A pre-Iter-10 engine that multiplied ``len(sources) * (end-start+1)``
    using the default envelope would emit ``total_pages_planned=20`` here.
    """
    spec = EngineRunSpec(
        sources=[_src("Alpha"), _src("Beta")],
        start_page=1,
        end_page=10,  # widest default
        time_range_start=date(2026, 1, 1),
        per_source_pages={"Alpha": (1, 3), "Beta": (1, 10)},
    )
    bus = ProgressBus()
    with _patch_layer1():
        engine.run(spec, bus=bus, max_workers=2)

    started = next(e for e in bus.drain() if isinstance(e, RunStarted))
    assert started.total_pages_planned == 13


def test_per_source_bounds_passed_to_run_url_params_source() -> None:
    """Spy on ``run_url_params_source`` calls and assert each source got
    *its own* envelope rather than a shared one."""
    spec = EngineRunSpec(
        sources=[_src("Alpha"), _src("Beta")],
        start_page=1,
        end_page=10,
        time_range_start=date(2026, 1, 1),
        per_source_pages={"Alpha": (1, 3), "Beta": (4, 7)},
    )
    seen: dict[str, tuple[int, int]] = {}

    def _spy(src, *, start_page, end_page, **kwargs):  # type: ignore[no-untyped-def]
        from scraper.runner import RunStats, SourceRunResult

        seen[src.name] = (start_page, end_page)
        return SourceRunResult(items=[], stats=RunStats(source_name=src.name))

    with _patch_layer1(), mock.patch("scraper.engine.run_url_params_source", side_effect=_spy):
        engine.run(spec, max_workers=2)

    assert seen == {"Alpha": (1, 3), "Beta": (4, 7)}


def test_default_bounds_used_when_per_source_pages_empty() -> None:
    """Backward-compat: callers that don't populate the dict get the old
    behaviour (every source uses the default envelope)."""
    spec = EngineRunSpec(
        sources=[_src("Alpha"), _src("Beta")],
        start_page=2,
        end_page=5,
        time_range_start=date(2026, 1, 1),
    )
    seen: dict[str, tuple[int, int]] = {}

    def _spy(src, *, start_page, end_page, **kwargs):  # type: ignore[no-untyped-def]
        from scraper.runner import RunStats, SourceRunResult

        seen[src.name] = (start_page, end_page)
        return SourceRunResult(items=[], stats=RunStats(source_name=src.name))

    with _patch_layer1(), mock.patch("scraper.engine.run_url_params_source", side_effect=_spy):
        engine.run(spec, max_workers=2)

    assert seen == {"Alpha": (2, 5), "Beta": (2, 5)}
