"""Scraping engine orchestrator.

Iter 4: runs each enabled source in its own thread via a
``ThreadPoolExecutor``, writing lifecycle events to a ``ProgressBus`` as
they happen. The Streamlit UI polls the bus from its own rerun loop, so
this module stays 100% Streamlit-free and fully unit-testable headless.

Public API — ``run(spec, bus=None, max_workers=None)`` — is a thin wrapper
that blocks until every source finishes. For the UI, ``utils.async_bridge``
wraps it in a background thread so the main Streamlit script keeps running.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date

from config import ScrapeSource
from scraper.pagination import needs_browser
from scraper.progress import (
    ProgressBus,
    RunFinished,
    RunStarted,
    SourceFinished,
)
from scraper.runner import SourceRunResult, run_browser_source, run_url_params_source

logger = logging.getLogger(__name__)


@dataclass
class EngineRunSpec:
    """Inputs a caller assembles once and hands to ``run``."""

    sources: list[ScrapeSource]
    start_page: int
    end_page: int
    time_range_start: date
    time_range_end: date | None = None


def _enabled(sources: list[ScrapeSource]) -> list[ScrapeSource]:
    return [s for s in sources if s.enabled]


def _default_worker_count(n_sources: int) -> int:
    """Cap parallelism so we don't fan out to 100 threads on a huge config.

    Most machines saturate origin servers well before 8 parallel fetches —
    past that point you're just making the site angry with no throughput
    gain. Empirically-chosen cap.
    """
    return max(1, min(n_sources, 8))


def run(
    spec: EngineRunSpec,
    bus: ProgressBus | None = None,
    max_workers: int | None = None,
) -> list[SourceRunResult]:
    """Run each enabled source in parallel, returning results in source order.

    The returned list order matches ``spec.sources`` (filtered to enabled),
    **not** completion order, so downstream code (pivot tables, etc.) can
    rely on it being deterministic.
    """
    sources = _enabled(spec.sources)
    workers = max_workers if max_workers is not None else _default_worker_count(len(sources))

    # Even if the caller doesn't pass a bus, we still want *something* to
    # emit into so the run lifecycle is consistent.
    bus = bus if bus is not None else ProgressBus()

    total_pages_planned = len(sources) * max(0, spec.end_page - spec.start_page + 1)
    bus.emit(
        RunStarted(
            source_names=[s.name for s in sources],
            total_pages_planned=total_pages_planned,
        )
    )

    results_by_name: dict[str, SourceRunResult] = {}

    if not sources:
        bus.emit(RunFinished(total_items=0, cancelled=False))
        return []

    def _run_one(src: ScrapeSource) -> SourceRunResult:
        try:
            if needs_browser(src):
                result = run_browser_source(
                    src,
                    start_page=spec.start_page,
                    end_page=spec.end_page,
                    time_range_start=spec.time_range_start,
                    time_range_end=spec.time_range_end,
                    bus=bus,
                )
            else:
                result = run_url_params_source(
                    src,
                    start_page=spec.start_page,
                    end_page=spec.end_page,
                    time_range_start=spec.time_range_start,
                    time_range_end=spec.time_range_end,
                    bus=bus,
                )
        except Exception:  # pragma: no cover - exercised in integration tests
            logger.exception("source %s crashed", src.name)
            # Return an empty result so the whole run still finishes cleanly.
            from scraper.runner import RunStats

            return SourceRunResult(
                items=[],
                stats=RunStats(
                    source_name=src.name,
                    errors=["unhandled exception in source runner"],
                ),
            )
        bus.emit(SourceFinished(source_name=src.name, result=result))
        return result

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="scraper") as pool:
        # Submit in input order so the executor picks them up in order; rely
        # on the returned name→result dict for deterministic output ordering.
        futures = {pool.submit(_run_one, src): src.name for src in sources}
        for fut in futures:
            name = futures[fut]
            results_by_name[name] = fut.result()

    ordered = [results_by_name[s.name] for s in sources if s.name in results_by_name]
    total_items = sum(len(r.items) for r in ordered)
    bus.emit(RunFinished(total_items=total_items, cancelled=bus.is_cancelled()))
    return ordered


__all__ = ["EngineRunSpec", "run"]
