"""Tests for the Iter 12 post-scrape summary aggregation in progress_panel."""

from __future__ import annotations

from scraper.progress import RunFinished, RunStarted, SourceFinished
from scraper.runner import RunStats, SourceRunResult
from ui.components.progress_panel import (
    ProgressSnapshot,
    SourceSummary,
    _apply_events,
)


def _make_finished_event(
    name: str,
    *,
    pages_scanned: int = 1,
    pages_failed: int = 0,
    items_in_range: int = 1,
    early_stopped: bool = False,
    early_stop_reason: str | None = None,
    page_failures: list | None = None,
    zero_hit: int = 0,
) -> SourceFinished:
    stats = RunStats(
        source_name=name,
        pages_scanned=pages_scanned,
        pages_failed=pages_failed,
        items_in_range=items_in_range,
        layer_usage={1: pages_scanned - pages_failed} if pages_scanned > pages_failed else {},
        early_stopped=early_stopped,
        early_stop_reason=early_stop_reason,
        page_failures=list(page_failures or []),
        pages_with_zero_hits=zero_hit,
    )
    return SourceFinished(source_name=name, result=SourceRunResult(items=[], stats=stats))


def test_source_summary_populated_from_source_finished_events():
    snap = ProgressSnapshot()
    _apply_events(
        snap,
        [
            RunStarted(source_names=["A", "B"], total_pages_planned=4),
            _make_finished_event(
                "A",
                pages_scanned=2,
                items_in_range=4,
                early_stopped=True,
                early_stop_reason="page 2: saw item dated before 2026-04-01",
            ),
            _make_finished_event(
                "B",
                pages_scanned=2,
                pages_failed=1,
                items_in_range=2,
                page_failures=[
                    {"page": "2", "url": "https://b.example/p=2", "error": "all layers failed"}
                ],
                zero_hit=1,
            ),
            RunFinished(total_items=6, cancelled=False),
        ],
    )
    assert len(snap.source_summaries) == 2
    by_name = {s.source_name: s for s in snap.source_summaries}
    assert isinstance(by_name["A"], SourceSummary)
    assert by_name["A"].early_stopped is True
    assert "page 2" in by_name["A"].early_stop_reason
    assert by_name["B"].pages_failed == 1
    assert len(by_name["B"].page_failures) == 1
    assert by_name["B"].pages_with_zero_hits == 1


def test_clean_run_summaries_have_no_notable_events():
    snap = ProgressSnapshot()
    _apply_events(
        snap,
        [
            RunStarted(source_names=["A"], total_pages_planned=1),
            _make_finished_event("A", pages_scanned=1, items_in_range=3),
            RunFinished(total_items=3, cancelled=False),
        ],
    )
    assert len(snap.source_summaries) == 1
    s = snap.source_summaries[0]
    assert not s.early_stopped
    assert not s.page_failures
    assert s.pages_with_zero_hits == 0
