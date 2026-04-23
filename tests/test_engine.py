"""Engine-level orchestration tests.

The engine in Iter 3 is intentionally single-threaded; these tests pin down
that:
- Disabled sources are skipped.
- Each enabled source produces exactly one ``SourceRunResult``.
- Ordering of results matches the input source list.

Iter 4 will replace the engine body with a ``ThreadPoolExecutor`` + async
progress bus; the public API in this test must remain backwards-compatible.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest import mock

from config import ScraperSelectors, ScrapeSource, SleepRange
from scraper import engine
from scraper.engine import EngineRunSpec
from scraper.layers.base import FetchResult

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
    name = "fake"
    layer_number = 1

    def fetch(self, url: str, timeout: float = 20.0) -> FetchResult:
        return FetchResult(url=url, html=PAGE1, status_code=200)


def test_engine_runs_each_enabled_source_once():
    spec = EngineRunSpec(
        sources=[_src("Alpha"), _src("Beta"), _src("Gamma", enabled=False)],
        start_page=1,
        end_page=1,
        time_range_start=date(2026, 1, 1),
        time_range_end=date(2026, 1, 31),
    )

    # Patch the runner to avoid any real fetcher construction.
    with mock.patch("scraper.engine.run_layer1_source") as runner:
        runner.side_effect = lambda src, **kw: mock.Mock(
            items=[], stats=mock.Mock(source_name=src.name)
        )
        results = engine.run(spec)

    assert [r.stats.source_name for r in results] == ["Alpha", "Beta"]
    assert runner.call_count == 2


def test_engine_preserves_source_order():
    spec = EngineRunSpec(
        sources=[_src("B"), _src("A"), _src("C")],
        start_page=1,
        end_page=1,
        time_range_start=date(2026, 1, 1),
    )
    with mock.patch("scraper.engine.run_layer1_source") as runner:
        runner.side_effect = lambda src, **kw: mock.Mock(
            items=[], stats=mock.Mock(source_name=src.name)
        )
        results = engine.run(spec)
    assert [r.stats.source_name for r in results] == ["B", "A", "C"]
