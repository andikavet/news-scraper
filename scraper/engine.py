"""Scraping engine orchestrator.

For Iteration 3 this is intentionally single-threaded: it loops over selected
sources sequentially and calls ``run_layer1_source`` for each. Iteration 4
replaces the body with a ``ThreadPoolExecutor`` + async progress bus that
never blocks the Streamlit UI.

The public API is the ``run`` function, which is the one boundary ``ui/``
will cross — everything below it stays free of Streamlit imports.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from config import ScrapeSource
from scraper.runner import SourceRunResult, run_layer1_source

logger = logging.getLogger(__name__)


@dataclass
class EngineRunSpec:
    """Inputs a caller assembles once and hands to ``run``."""

    sources: list[ScrapeSource]
    start_page: int
    end_page: int
    time_range_start: date
    time_range_end: date | None = None


def run(spec: EngineRunSpec) -> list[SourceRunResult]:
    """Run each enabled source sequentially and return one result per source.

    Disabled sources (``source.enabled == False``) are skipped.
    """
    results: list[SourceRunResult] = []
    for source in spec.sources:
        if not source.enabled:
            logger.info("skipping disabled source %s", source.name)
            continue
        logger.info("running source %s", source.name)
        results.append(
            run_layer1_source(
                source,
                start_page=spec.start_page,
                end_page=spec.end_page,
                time_range_start=spec.time_range_start,
                time_range_end=spec.time_range_end,
            )
        )
    return results


__all__ = ["EngineRunSpec", "run"]
