"""End-to-end test for the Iter 9 block-detection escalate path.

Kept separate from ``test_runner_fallback.py`` so the two escalate
triggers (ScrapeError vs. 2xx-block) stay independently pinned. Broken
wiring between the block detector and the orchestrator should fail these
tests without touching the Iter 8 baseline.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from config import ScraperSelectors, ScrapeSource, SleepRange
from scraper.fetch_orchestrator import FetchOrchestrator, default_block_detector
from scraper.layers.base import FetchResult
from scraper.progress import PageFetched, ProgressBus
from scraper.runner import run_url_params_source

FIXTURES = Path(__file__).parent / "fixtures"
PAGE1 = (FIXTURES / "portalx_listing.html").read_text(encoding="utf-8")
PAGE2 = (FIXTURES / "portalx_page2.html").read_text(encoding="utf-8")

CLOUDFLARE_HTML = (
    "<!DOCTYPE html><html><head><title>Just a moment...</title></head>"
    '<body><div class="cf-browser-verification">Checking your browser</div>'
    "</body></html>"
)


def _src() -> ScrapeSource:
    return ScrapeSource(
        name="PortalX",
        pagination_type="url_params",
        url_template="https://portalx.test/news?page={page}",
        selectors=ScraperSelectors(
            container="li.article-item", title="h2", link="h2 a", date="span.date-time"
        ),
        sleep=SleepRange(min=0.0, max=0.0),
        max_retries=0,
        enabled_layers=[1, 2],
    )


class _StaticLayer:
    """Minimal layer that returns a pre-canned HTML per URL."""

    def __init__(
        self,
        layer_number: int,
        name: str,
        parser_name: str,
        pages_by_url: dict[str, str],
    ) -> None:
        self.layer_number = layer_number
        self.name = name
        self.parser_name = parser_name
        self.pages_by_url = dict(pages_by_url)
        self.calls: list[str] = []

    def fetch(self, url: str, timeout: float = 20.0) -> FetchResult:
        self.calls.append(url)
        return FetchResult(
            url=url,
            html=self.pages_by_url.get(url, "<html/>"),
            status_code=200,
        )


def _noop(_: float) -> None:
    return None


URL1 = "https://portalx.test/news?page=1"
URL2 = "https://portalx.test/news?page=2"
REF = date(2026, 1, 15)


def test_runner_escalates_on_cloudflare_html_even_though_status_is_200() -> None:
    """Layer 1 returns 200 + Cloudflare HTML → runner escalates to Layer 2."""
    l1 = _StaticLayer(1, "l1", "bs4", {URL1: CLOUDFLARE_HTML, URL2: CLOUDFLARE_HTML})
    l2 = _StaticLayer(2, "l2", "selectolax", {URL1: PAGE1, URL2: PAGE2})
    orch = FetchOrchestrator([l1, l2], block_detector=default_block_detector)

    result = run_url_params_source(
        _src(),
        start_page=1,
        end_page=2,
        time_range_start=date(2026, 1, 1),
        orchestrator=orch,
        sleeper=_noop,
        reference_date=REF,
    )

    # Layer 1 must be attempted for each page (the block is discovered on
    # the 200 response) but Layer 2 always delivers.
    assert l1.calls == [URL1, URL2]
    assert l2.calls == [URL1, URL2]
    assert result.stats.pages_scanned == 2
    assert result.stats.pages_failed == 0
    assert result.stats.layer_usage == {2: 2}
    # Content parity with the un-blocked baseline.
    titles = [item.title for item in result.items]
    assert "Inflasi turun ke 2,3% bulan ini" in titles


def test_page_fetched_event_reports_layer_2_when_layer_1_soft_blocked() -> None:
    """Progress bus must see ``layer_used=2`` on the event so the UI can
    surface which layer actually served the page."""
    l1 = _StaticLayer(1, "l1", "bs4", {URL1: CLOUDFLARE_HTML})
    l2 = _StaticLayer(2, "l2", "selectolax", {URL1: PAGE1})
    orch = FetchOrchestrator([l1, l2], block_detector=default_block_detector)

    bus = ProgressBus()
    run_url_params_source(
        _src(),
        start_page=1,
        end_page=1,
        time_range_start=date(2026, 1, 1),
        orchestrator=orch,
        sleeper=_noop,
        reference_date=REF,
        bus=bus,
    )

    page_events = [e for e in bus.drain() if isinstance(e, PageFetched)]
    assert len(page_events) == 1
    assert page_events[0].layer_used == 2
    assert page_events[0].items_scanned > 0
