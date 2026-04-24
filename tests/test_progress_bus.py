"""Progress bus smoke tests."""

from __future__ import annotations

import pytest

from scraper.progress import (
    PageFailed,
    PageFetched,
    ProgressBus,
    RunFinished,
    RunStarted,
    SourceFinished,
    SourceStarted,
)
from scraper.runner import RunStats, SourceRunResult


def test_bus_drain_returns_events_in_emit_order():
    bus = ProgressBus()
    bus.emit(RunStarted(source_names=["A"], total_pages_planned=3))
    bus.emit(SourceStarted(source_name="A", total_pages=3))
    bus.emit(PageFetched(source_name="A", page=1, items_scanned=10, items_in_range=7))
    bus.emit(PageFailed(source_name="A", page=2, error="boom"))
    result = SourceRunResult(items=[], stats=RunStats(source_name="A"))
    bus.emit(SourceFinished(source_name="A", result=result))
    bus.emit(RunFinished(total_items=7, cancelled=False))

    events = bus.drain()
    assert [type(e).__name__ for e in events] == [
        "RunStarted",
        "SourceStarted",
        "PageFetched",
        "PageFailed",
        "SourceFinished",
        "RunFinished",
    ]


def test_bus_drain_is_destructive():
    bus = ProgressBus()
    bus.emit(RunFinished(total_items=0, cancelled=False))
    assert len(bus.drain()) == 1
    assert bus.drain() == []


def test_bus_cancellation_flag():
    bus = ProgressBus()
    assert bus.is_cancelled() is False
    bus.cancel()
    assert bus.is_cancelled() is True


def test_bus_is_finished_flag():
    bus = ProgressBus()
    assert bus.is_finished() is False
    bus.emit(SourceStarted(source_name="A", total_pages=1))
    assert bus.is_finished() is False
    bus.emit(RunFinished(total_items=0, cancelled=False))
    assert bus.is_finished() is True


def test_pagefetched_is_immutable():
    e = PageFetched(source_name="A", page=1, items_scanned=10, items_in_range=7)
    with pytest.raises((AttributeError, TypeError)):
        e.page = 2  # type: ignore[misc]
