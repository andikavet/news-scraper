"""Per-source scraping loop.

Runs one configured ``ScrapeSource`` through Layer 1 (``httpx`` + BeautifulSoup),
iterates pages via the ``url_params`` pagination strategy, parses dates, and
short-circuits (*early-stops*) as soon as a parsed article date falls below
the user-selected time range start. Returns the collected ``NewsItem``s plus
a ``RunStats`` record summarizing what happened.

Design notes / tradeoffs:

- Retries are **per-fetch** only. A page that fails all retries is logged and
  the loop continues to the next page — one bad page must never kill the
  whole source, per PRD §2.4.
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
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from config import ScrapeSource
from scraper.date_parser import parse_scraped_date
from scraper.layers.base import FetchResult, ScrapeError
from scraper.layers.layer1_httpx import Layer1Httpx
from scraper.models import NewsItem, RawScrapeHit
from scraper.pagination import iter_page_requests
from scraper.parsers import extract_items

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


@dataclass
class SourceRunResult:
    items: list[NewsItem]
    stats: RunStats


# --------------------------------------------------------------------------- #
# Core loop
# --------------------------------------------------------------------------- #


def _fetch_with_retries(
    fetcher: _Fetcher,
    url: str,
    max_retries: int,
    sleep: Sleeper,
    retry_backoff: float = 2.0,
) -> FetchResult | None:
    """Try ``fetch`` up to ``max_retries + 1`` times; return None on final failure.

    Sleep between retries grows linearly (1x, 2x, 3x ``retry_backoff``).
    """
    attempts = max_retries + 1
    last_err: str | None = None
    for attempt in range(attempts):
        try:
            return fetcher.fetch(url)
        except ScrapeError as e:
            last_err = str(e)
            logger.warning(
                "layer %s fetch failed (attempt %d/%d): %s", fetcher.name, attempt + 1, attempts, e
            )
            if attempt + 1 < attempts:
                sleep(retry_backoff * (attempt + 1))
    logger.error("all %d attempts failed for %s: %s", attempts, url, last_err)
    return None


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


def run_layer1_source(
    source: ScrapeSource,
    start_page: int,
    end_page: int,
    time_range_start: date,
    time_range_end: date | None = None,
    *,
    fetcher: _Fetcher | None = None,
    sleeper: Sleeper | None = None,
    rng: random.Random | None = None,
    reference_date: date | None = None,
) -> SourceRunResult:
    """Scrape one source end-to-end via Layer 1.

    Parameters beyond the source/config are injectable so the runner is fully
    unit-testable without touching the network or the wall clock.
    """
    if start_page < 1 or end_page < start_page:
        raise ValueError(f"invalid page range: start_page={start_page} end_page={end_page}")

    fetcher = fetcher if fetcher is not None else Layer1Httpx()
    sleep = sleeper if sleeper is not None else _default_sleep
    rng = rng if rng is not None else random.Random()
    ref = reference_date if reference_date is not None else date.today()

    stats = RunStats(source_name=source.name)
    items: list[NewsItem] = []

    for req in iter_page_requests(source, start_page=start_page, end_page=end_page):
        fetched = _fetch_with_retries(
            fetcher=fetcher,
            url=req.url,
            max_retries=source.max_retries,
            sleep=sleep,
        )
        stats.pages_scanned += 1
        if fetched is None:
            stats.pages_failed += 1
            stats.errors.append(f"page {req.page}: all retries failed")
            continue

        hits = extract_items(fetched.html, source.selectors)
        stats.items_scanned += len(hits)

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
            else:
                stats.items_out_of_range += 1

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


def _default_sleep(seconds: float) -> None:
    """Real-clock sleep. Split out so tests inject a no-op sleeper."""
    import time

    time.sleep(seconds)


__all__ = [
    "RunStats",
    "Sleeper",
    "SourceRunResult",
    "run_layer1_source",
]
