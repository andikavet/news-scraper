"""Iter 12 diagnostics on RunStats: early_stop_reason, page_failures, zero-hit pages."""

from __future__ import annotations

from datetime import date

from config import ScraperSelectors, ScrapeSource
from scraper.fetch_orchestrator import FetchOrchestrator
from scraper.layers.base import FetchResult
from scraper.runner import run_url_params_source

_HTML_TWO = """
<ul>
  <li class='card'><h2><a href='/a'>A</a></h2><span class='date'>10 Apr 2026</span></li>
  <li class='card'><h2><a href='/b'>B</a></h2><span class='date'>09 Apr 2026</span></li>
</ul>
"""
_HTML_OLD = """
<ul>
  <li class='card'><h2><a href='/x'>X</a></h2><span class='date'>10 Jan 2025</span></li>
</ul>
"""
_HTML_EMPTY = "<html><body></body></html>"


def _src() -> ScrapeSource:
    return ScrapeSource(
        name="Test",
        pagination_type="url_params",
        url_template="https://example.com/p={page}",
        selectors=ScraperSelectors(container="li.card", title="h2 a", link="h2 a", date=".date"),
        avg_page_per_month=1,
        max_retries=0,
        enabled_layers=[1],
    )


class _ScriptedLayer:
    name = "scripted"
    layer_number = 1
    parser_name = "bs4"

    def __init__(self, htmls: list[str]) -> None:
        self._htmls = list(htmls)

    def fetch(self, url: str, timeout: float = 20.0) -> FetchResult:  # noqa: ARG002
        html = self._htmls.pop(0) if self._htmls else "<html></html>"
        return FetchResult(url=url, html=html, status_code=200)


class _AlwaysFailLayer:
    name = "always_fail"
    layer_number = 1
    parser_name = "bs4"

    def fetch(self, url: str, timeout: float = 20.0):  # noqa: ARG002
        from scraper.layers.base import ScrapeError

        raise ScrapeError(f"synthetic failure for {url}")


def test_early_stop_reason_records_page_and_boundary_date():
    """When a page yields a date below range start, stash a structured reason."""
    orch = FetchOrchestrator([_ScriptedLayer([_HTML_TWO, _HTML_OLD, _HTML_TWO])])
    result = run_url_params_source(
        _src(),
        start_page=1,
        end_page=3,
        time_range_start=date(2026, 4, 1),
        orchestrator=orch,
        sleeper=lambda _s: None,
        reference_date=date(2026, 4, 23),
    )
    assert result.stats.early_stopped is True
    assert result.stats.early_stop_reason is not None
    assert "page 2" in result.stats.early_stop_reason
    # The boundary date should be embedded so the UI can show "below 2026-04-01".
    assert "2026-04-01" in result.stats.early_stop_reason


def test_page_failures_capture_url_and_error():
    """Every failed page gets a structured row, not just a free-form message."""
    orch = FetchOrchestrator([_AlwaysFailLayer()])
    result = run_url_params_source(
        _src(),
        start_page=1,
        end_page=2,
        time_range_start=date(2026, 1, 1),
        orchestrator=orch,
        sleeper=lambda _s: None,
        reference_date=date(2026, 4, 23),
    )
    assert result.stats.pages_failed == 2
    assert len(result.stats.page_failures) == 2
    first = result.stats.page_failures[0]
    assert first["page"] == "1"
    assert "p=1" in first["url"]
    assert "synthetic failure" in first["error"]


def test_pages_with_zero_hits_counts_successful_but_empty_responses():
    """Successful 200 responses that yield zero rows signal selector mismatch."""
    orch = FetchOrchestrator([_ScriptedLayer([_HTML_TWO, _HTML_EMPTY, _HTML_TWO])])
    result = run_url_params_source(
        _src(),
        start_page=1,
        end_page=3,
        time_range_start=date(2026, 1, 1),
        orchestrator=orch,
        sleeper=lambda _s: None,
        reference_date=date(2026, 4, 23),
    )
    # One of the three pages had no containers → counted as a zero-hit page.
    assert result.stats.pages_with_zero_hits == 1
    assert result.stats.pages_failed == 0  # zero-hits is NOT a failure
    assert result.stats.pages_scanned == 3


def test_clean_run_keeps_diagnostics_at_zero():
    """Healthy runs should not allocate spurious failure rows."""
    orch = FetchOrchestrator([_ScriptedLayer([_HTML_TWO, _HTML_TWO])])
    result = run_url_params_source(
        _src(),
        start_page=1,
        end_page=2,
        time_range_start=date(2026, 1, 1),
        orchestrator=orch,
        sleeper=lambda _s: None,
        reference_date=date(2026, 4, 23),
    )
    assert result.stats.early_stopped is False
    assert result.stats.early_stop_reason is None
    assert result.stats.page_failures == []
    assert result.stats.pages_with_zero_hits == 0
