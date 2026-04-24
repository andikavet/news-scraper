"""Per-source scraping loop.

Runs one configured ``ScrapeSource`` through the Layer cascade
(``FetchOrchestrator``), iterates pages via the ``url_params`` pagination
strategy, parses dates, and short-circuits (*early-stops*) as soon as a
parsed article date falls below the user-selected time range start. Returns
the collected ``NewsItem``s plus a ``RunStats`` record summarizing what
happened — including which layer delivered each page.

Design notes / tradeoffs:

- Retries are **per-layer** and stack with fallback: the orchestrator retries
  each layer ``max_retries + 1`` times before escalating, and only declares
  a page failed once every enabled layer has exhausted its attempts.
- Sleep between successful page fetches is sampled uniformly from
  ``source.sleep`` — light rate-limiting to avoid hammering the origin.
- Items with an unparseable ``date_raw`` are **kept** (the user wants to see
  and fix them) but they do **not** trigger early-stop, since a single
  unparseable row below the range start would otherwise hide the signal that
  older content is coming next.
- Items with a parseable date that falls outside the range are **dropped**
  from the returned list but still counted towards ``items_scanned``.
- Zero Streamlit imports. The runner is a pure function of its inputs and an
  injectable ``Sleeper`` / ``Clock`` — callable from the UI thread OR from a
  background worker OR from a unit test indistinguishably.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Protocol

from config import ScrapeSource
from scraper.date_parser import parse_scraped_date
from scraper.fetch_orchestrator import FetchOrchestrator, build_layers_for_source
from scraper.layers.base import FetchResult
from scraper.models import NewsItem, RawScrapeHit
from scraper.pagination import iter_page_requests
from scraper.parsers import extract_items, parse_for
from scraper.playwright_session import (
    BrowserSessionError,
    browser_page,
    iter_click_next_pages,
    iter_infinite_scroll_pages,
)

if TYPE_CHECKING:
    from playwright.sync_api import Page  # noqa: F401  (used in type hints only)

    from scraper.progress import ProgressBus

logger = logging.getLogger(__name__)

Sleeper = Callable[[float], None]


class _Fetcher(Protocol):
    name: str
    layer_number: int

    def fetch(self, url: str, timeout: float = 20.0) -> FetchResult: ...


# --------------------------------------------------------------------------- #
# Result + stats
# --------------------------------------------------------------------------- #


@dataclass
class RunStats:
    """Run-level metrics returned alongside the ``NewsItem`` list."""

    source_name: str
    pages_scanned: int = 0
    pages_failed: int = 0
    items_scanned: int = 0
    items_in_range: int = 0
    items_out_of_range: int = 0
    items_undated: int = 0
    early_stopped: bool = False
    errors: list[str] = field(default_factory=list)
    # Iter 8: count of successfully-fetched pages per layer number. Lets the
    # user see at a glance "all 12 pages were served by Layer 1" vs "Layer 1
    # bounced 8 of them and Layer 2 picked up the slack".
    layer_usage: dict[int, int] = field(default_factory=dict)


@dataclass
class SourceRunResult:
    items: list[NewsItem]
    stats: RunStats


# --------------------------------------------------------------------------- #
# Core loop
# --------------------------------------------------------------------------- #


def _orchestrator_from_param(
    orchestrator: FetchOrchestrator | None,
    fetcher: _Fetcher | None,
    source: ScrapeSource,
) -> FetchOrchestrator:
    """Resolve the caller-supplied orchestrator / legacy fetcher into a concrete orchestrator.

    Priority:
    1. ``orchestrator`` if given — used as-is.
    2. ``fetcher`` (single layer, legacy callers / tests) — wrapped in a
       1-layer orchestrator, no fallback.
    3. Neither — build from ``source.enabled_layers`` via
       :func:`build_layers_for_source`.
    """
    if orchestrator is not None:
        return orchestrator
    if fetcher is not None:
        return FetchOrchestrator([fetcher])
    return FetchOrchestrator(build_layers_for_source(source))


def _inrange(d: date | None, start: date, end: date | None) -> bool:
    """Range is inclusive on both ends."""
    if d is None:
        return True  # undated items are kept; the caller counts them separately.
    if d < start:
        return False
    return not (end is not None and d > end)


def _hit_to_news_item(
    hit: RawScrapeHit,
    source_name: str,
    page: int,
    reference: date,
) -> NewsItem:
    parsed = parse_scraped_date(hit.date_raw, reference=reference)
    return NewsItem(
        title=hit.title,
        link=hit.link,
        date_raw=hit.date_raw,
        date_parsed=parsed,
        source=source_name,
        page=page,
    )


def run_url_params_source(
    source: ScrapeSource,
    start_page: int,
    end_page: int,
    time_range_start: date,
    time_range_end: date | None = None,
    *,
    orchestrator: FetchOrchestrator | None = None,
    fetcher: _Fetcher | None = None,
    sleeper: Sleeper | None = None,
    rng: random.Random | None = None,
    reference_date: date | None = None,
    bus: ProgressBus | None = None,
) -> SourceRunResult:
    """Scrape one ``url_params`` source end-to-end, with Layer 1 → N fallback.

    For each page, the :class:`FetchOrchestrator` tries every enabled layer
    (in config order) before giving up. Whichever layer succeeds first is
    recorded in :attr:`RunStats.layer_usage` and attached to the
    :class:`~scraper.progress.PageFetched` event.

    Parameters beyond the source/config are injectable so the runner is
    fully unit-testable without touching the network or the wall clock. If
    ``bus`` is provided, lifecycle events are emitted and the runner checks
    ``bus.is_cancelled()`` before fetching each page.

    Backward-compat: passing ``fetcher=`` wraps a single layer in a
    1-element orchestrator (no fallback). This keeps the Iter 3 tests that
    drive the runner with a canned ``_FakeFetcher`` working unchanged.
    """
    if start_page < 1 or end_page < start_page:
        raise ValueError(f"invalid page range: start_page={start_page} end_page={end_page}")

    orch = _orchestrator_from_param(orchestrator, fetcher, source)
    sleep = sleeper if sleeper is not None else _default_sleep
    rng = rng if rng is not None else random.Random()
    ref = reference_date if reference_date is not None else date.today()

    stats = RunStats(source_name=source.name)
    items: list[NewsItem] = []

    total_pages = end_page - start_page + 1
    if bus is not None:
        from scraper.progress import SourceStarted

        bus.emit(SourceStarted(source_name=source.name, total_pages=total_pages))

    for req in iter_page_requests(source, start_page=start_page, end_page=end_page):
        if bus is not None and bus.is_cancelled():
            logger.info("source %s: cancelled before page %d", source.name, req.page)
            break

        outcome, per_layer_errors = orch.fetch_with_fallback(
            url=req.url,
            max_retries=source.max_retries,
            sleep=sleep,
        )
        stats.pages_scanned += 1
        if outcome is None:
            stats.pages_failed += 1
            stats.errors.append(
                f"page {req.page}: all layers failed ({'; '.join(per_layer_errors)})"
            )
            if bus is not None:
                from scraper.progress import PageFailed

                bus.emit(
                    PageFailed(
                        source_name=source.name,
                        page=req.page,
                        error="all enabled layers failed",
                    )
                )
            continue

        stats.layer_usage[outcome.layer_number] = stats.layer_usage.get(outcome.layer_number, 0) + 1

        hits = parse_for(outcome.parser_name, outcome.fetched.html, source.selectors)
        stats.items_scanned += len(hits)

        page_in_range = 0
        oldest_seen_below_range = False
        for hit in hits:
            item = _hit_to_news_item(hit, source.name, req.page, ref)
            if item.date_parsed is None:
                stats.items_undated += 1
            elif item.date_parsed < time_range_start:
                oldest_seen_below_range = True

            if _inrange(item.date_parsed, time_range_start, time_range_end):
                items.append(item)
                stats.items_in_range += 1
                page_in_range += 1
            else:
                stats.items_out_of_range += 1

        if bus is not None:
            from scraper.progress import PageFetched

            bus.emit(
                PageFetched(
                    source_name=source.name,
                    page=req.page,
                    items_scanned=len(hits),
                    items_in_range=page_in_range,
                    layer_used=outcome.layer_number,
                )
            )

        if oldest_seen_below_range:
            stats.early_stopped = True
            logger.info(
                "source %s: early-stopping at page %d (saw date below range start)",
                source.name,
                req.page,
            )
            break

        # Inter-page sleep — skip after the *last* page we'll fetch.
        if req.page < end_page:
            sleep(rng.uniform(source.sleep.min, source.sleep.max))

    return SourceRunResult(items=items, stats=stats)


#: Backward-compat alias. Iter 3 tests and the pre-Iter-8 engine entry point
#: called this ``run_layer1_source``; the name was always a misnomer (the
#: function could run any Layer-shaped fetcher) so the Iter 8 rename makes
#: it explicit. Existing call-sites continue to work without edits.
run_layer1_source = run_url_params_source


def _default_sleep(seconds: float) -> None:
    """Real-clock sleep. Split out so tests inject a no-op sleeper."""
    import time

    time.sleep(seconds)


# --------------------------------------------------------------------------- #
# Browser-driven runner (Iter 7)
# --------------------------------------------------------------------------- #


def _process_page_hits(
    hits: list[RawScrapeHit],
    *,
    source_name: str,
    page: int,
    reference: date,
    time_range_start: date,
    time_range_end: date | None,
    stats: RunStats,
    items: list[NewsItem],
    seen_links: set[str],
) -> tuple[int, bool]:
    """Convert raw hits → NewsItems with dedup, update stats, return (new_in_range, early_stop).

    Shared between the Layer 1 runner and the browser-driven runner. The
    ``seen_links`` set is mutated in place so infinite-scroll callers don't
    double-count items that were already captured in an earlier snapshot.
    """
    new_in_range = 0
    oldest_seen_below_range = False
    for hit in hits:
        if hit.link in seen_links:
            continue
        seen_links.add(hit.link)
        item = _hit_to_news_item(hit, source_name, page, reference)
        stats.items_scanned += 1
        if item.date_parsed is None:
            stats.items_undated += 1
        elif item.date_parsed < time_range_start:
            oldest_seen_below_range = True

        if _inrange(item.date_parsed, time_range_start, time_range_end):
            items.append(item)
            stats.items_in_range += 1
            new_in_range += 1
        else:
            stats.items_out_of_range += 1
    return new_in_range, oldest_seen_below_range


def run_browser_source(
    source: ScrapeSource,
    start_page: int,
    end_page: int,
    time_range_start: date,
    time_range_end: date | None = None,
    *,
    session_factory: Callable[[], AbstractContextManager[Page]] | None = None,  # type: ignore[name-defined]
    reference_date: date | None = None,
    bus: ProgressBus | None = None,
) -> SourceRunResult:
    """Drive a JS-rendered listing via Playwright for ``infinite_scroll`` or ``click_next``.

    One browser session spans the whole run so intra-page state (scroll
    position, next-button context, XHR cookies) is preserved across pages.
    The runner consumes the page-snapshot iterator and applies the same
    date-parse + in-range + early-stop logic as :func:`run_layer1_source`.

    ``session_factory`` is exposed for tests that want to inject a fake
    ``browser_page`` context manager (e.g. file:// fixture URL) without
    duplicating navigation logic.
    """
    if start_page < 1 or end_page < start_page:
        raise ValueError(f"invalid page range: start_page={start_page} end_page={end_page}")
    if source.pagination_type not in ("infinite_scroll", "click_next"):
        raise ValueError(
            f"run_browser_source called with pagination_type={source.pagination_type!r}; "
            "expected 'infinite_scroll' or 'click_next'"
        )

    ref = reference_date if reference_date is not None else date.today()
    stats = RunStats(source_name=source.name)
    items: list[NewsItem] = []
    seen_links: set[str] = set()
    total_pages = end_page - start_page + 1

    if bus is not None:
        from scraper.progress import SourceStarted

        bus.emit(SourceStarted(source_name=source.name, total_pages=total_pages))

    def _should_stop() -> bool:
        return bus is not None and bus.is_cancelled()

    session_cm = session_factory() if session_factory is not None else browser_page()

    initial_url = source.url_template.replace("{page}", str(start_page))

    try:
        with session_cm as page:
            if source.pagination_type == "infinite_scroll":
                page_iter = iter_infinite_scroll_pages(
                    page,
                    url=initial_url,
                    start_page=start_page,
                    end_page=end_page,
                    scrolls_per_page=source.scrolls_per_page,
                    should_stop=_should_stop,
                )
            else:
                page_iter = iter_click_next_pages(
                    page,
                    url=initial_url,
                    next_button_selector=source.selectors.next_button,
                    start_page=start_page,
                    end_page=end_page,
                    should_stop=_should_stop,
                )

            for snap in page_iter:
                if _should_stop():
                    logger.info("source %s: cancelled before page %d", source.name, snap.page)
                    break
                hits = extract_items(snap.html, source.selectors)
                stats.pages_scanned += 1
                new_in_range, oldest_seen_below_range = _process_page_hits(
                    hits,
                    source_name=source.name,
                    page=snap.page,
                    reference=ref,
                    time_range_start=time_range_start,
                    time_range_end=time_range_end,
                    stats=stats,
                    items=items,
                    seen_links=seen_links,
                )
                if bus is not None:
                    from scraper.progress import PageFetched

                    bus.emit(
                        PageFetched(
                            source_name=source.name,
                            page=snap.page,
                            items_scanned=len(hits),
                            items_in_range=new_in_range,
                        )
                    )
                if oldest_seen_below_range:
                    stats.early_stopped = True
                    logger.info(
                        "source %s: early-stopping at page %d (saw date below range start)",
                        source.name,
                        snap.page,
                    )
                    break
    except BrowserSessionError as e:
        logger.error("source %s: browser session failed: %s", source.name, e)
        stats.pages_failed += 1
        stats.errors.append(f"browser session failed: {e}")

    return SourceRunResult(items=items, stats=stats)


__all__ = [
    "RunStats",
    "Sleeper",
    "SourceRunResult",
    "run_browser_source",
    "run_layer1_source",  # back-compat alias for run_url_params_source
    "run_url_params_source",
]
