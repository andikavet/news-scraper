"""Pin Iter 10's layer-usage badge wiring.

The completion banner shows ``Layer usage: L1=N, L2=M, ...`` so the user
can see the Iter 8/9 fallback cascade fire in real runs. The aggregation
happens in :func:`ui.components.progress_panel._apply_events` from each
``SourceFinished.result.stats.layer_usage`` dict.
"""

from __future__ import annotations

from scraper.progress import RunFinished, RunStarted, SourceFinished
from scraper.runner import RunStats, SourceRunResult
from ui.components.progress_panel import ProgressSnapshot, _apply_events


def _finished_event(name: str, layer_usage: dict[int, int]) -> SourceFinished:
    return SourceFinished(
        source_name=name,
        result=SourceRunResult(
            items=[],
            stats=RunStats(source_name=name, layer_usage=dict(layer_usage)),
        ),
    )


def test_layer_usage_aggregates_across_sources() -> None:
    """Two sources, one served entirely by L1 + one mixed → totals add."""
    snap = ProgressSnapshot()
    _apply_events(
        snap,
        [
            RunStarted(source_names=["A", "B"], total_pages_planned=10),
            _finished_event("A", {1: 5}),
            _finished_event("B", {1: 2, 2: 3}),
            RunFinished(total_items=10, cancelled=False),
        ],
    )
    assert snap.layer_usage == {1: 7, 2: 3}


def test_layer_usage_empty_when_no_sources_finished() -> None:
    snap = ProgressSnapshot()
    _apply_events(
        snap,
        [
            RunStarted(source_names=["A"], total_pages_planned=1),
            RunFinished(total_items=0, cancelled=True),
        ],
    )
    assert snap.layer_usage == {}


def test_layer_usage_handles_layer4_in_mix() -> None:
    """Stealth layer escalation gets its own L4 entry."""
    snap = ProgressSnapshot()
    _apply_events(
        snap,
        [
            RunStarted(source_names=["A"], total_pages_planned=4),
            _finished_event("A", {1: 1, 2: 1, 4: 2}),
            RunFinished(total_items=4, cancelled=False),
        ],
    )
    assert snap.layer_usage == {1: 1, 2: 1, 4: 2}


def test_layer_usage_accumulates_when_events_arrive_in_chunks() -> None:
    """Real fragments call ``_apply_events`` repeatedly with new event slices.
    The accumulated state must keep summing rather than replacing."""
    snap = ProgressSnapshot()
    _apply_events(
        snap,
        [RunStarted(source_names=["A", "B"], total_pages_planned=10)],
    )
    _apply_events(snap, [_finished_event("A", {1: 4})])
    assert snap.layer_usage == {1: 4}
    _apply_events(snap, [_finished_event("B", {1: 1, 2: 5})])
    assert snap.layer_usage == {1: 5, 2: 5}
