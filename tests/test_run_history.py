"""Run-history persistence tests.

Iter 11 — covers the load / append / cap-at-MAX_ENTRIES contract plus
the JSON round-trip through ``RunHistoryEntry``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from scraper.run_history import (
    MAX_ENTRIES,
    MAX_ERRORS_PER_ENTRY,
    RunHistoryEntry,
    append_entry,
    build_entry_from_results,
    history_path,
    load_entries,
)
from scraper.runner import RunStats, SourceRunResult


def _entry(label: str, *, total_items: int = 1) -> RunHistoryEntry:
    """Tiny factory; we don't care about the exact timestamp values."""
    now = datetime.now(UTC)
    return RunHistoryEntry(
        started_at=now,
        finished_at=now + timedelta(seconds=1),
        source_names=[label],
        total_items=total_items,
    )


def test_load_entries_returns_empty_when_file_missing():
    assert not history_path().exists()
    assert load_entries() == []


def test_append_then_load_roundtrip():
    e = _entry("Alpha", total_items=42)
    append_entry(e)

    [loaded] = load_entries()
    assert loaded.source_names == ["Alpha"]
    assert loaded.total_items == 42
    # Datetime round-trips through ISO 8601 — make sure tzinfo is preserved.
    assert loaded.started_at.tzinfo is not None
    assert loaded.duration_seconds >= 1.0


def test_append_orders_newest_first():
    append_entry(_entry("First"))
    append_entry(_entry("Second"))
    append_entry(_entry("Third"))

    loaded = load_entries()
    assert [e.source_names[0] for e in loaded] == ["Third", "Second", "First"]


def test_append_caps_at_max_entries():
    # Append MAX_ENTRIES + 5 entries — the oldest 5 must be dropped.
    for i in range(MAX_ENTRIES + 5):
        append_entry(_entry(f"run{i}"))

    loaded = load_entries()
    assert len(loaded) == MAX_ENTRIES
    # Newest still at the head, oldest entries silently fell off the tail.
    assert loaded[0].source_names == [f"run{MAX_ENTRIES + 4}"]
    assert loaded[-1].source_names == [f"run{5}"]


def test_layer_usage_summary_renders_in_order():
    e = _entry("Mixed")
    e = e.model_copy(update={"layer_usage": {2: 3, 1: 7, 4: 1}})
    assert e.layer_usage_summary() == "L1=7, L2=3, L4=1"


def test_layer_usage_summary_handles_empty():
    assert _entry("Empty").layer_usage_summary() == "(none)"


def test_corrupt_history_file_treated_as_empty(tmp_path, monkeypatch):
    # Reset the env var so this test gets its own dir (the autouse fixture
    # already did — we just want a fresh one with deliberately-bad content).
    monkeypatch.setenv("NEWS_SCRAPER_CONFIG_DIR", str(tmp_path))
    history_path().write_text("definitely not json {", encoding="utf-8")
    assert load_entries() == []


def test_build_entry_from_results_aggregates_per_source_stats():
    started = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    finished = datetime(2026, 1, 1, 9, 1, tzinfo=UTC)

    a = SourceRunResult(
        items=[],
        stats=RunStats(
            source_name="Alpha",
            pages_scanned=5,
            pages_failed=1,
            items_in_range=10,
            errors=["page 3: boom"],
            layer_usage={1: 4, 2: 1},
        ),
    )
    b = SourceRunResult(
        items=[],
        stats=RunStats(
            source_name="Beta",
            pages_scanned=3,
            pages_failed=0,
            items_in_range=2,
            errors=[],
            layer_usage={1: 3},
        ),
    )

    entry = build_entry_from_results(
        started_at=started,
        finished_at=finished,
        source_names=["Alpha", "Beta"],
        results=[a, b],
        cancelled=False,
    )

    assert entry.total_items == 12
    assert entry.pages_scanned == 8
    assert entry.pages_failed == 1
    assert entry.layer_usage == {1: 7, 2: 1}
    assert entry.error_count == 1
    assert entry.error_lines == ["Alpha: page 3: boom"]
    assert entry.cancelled is False


def test_build_entry_truncates_excessive_error_lines():
    # One source with way more errors than MAX_ERRORS_PER_ENTRY.
    n_errors = MAX_ERRORS_PER_ENTRY + 7
    result = SourceRunResult(
        items=[],
        stats=RunStats(
            source_name="Spammy",
            errors=[f"e{i}" for i in range(n_errors)],
        ),
    )
    entry = build_entry_from_results(
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        source_names=["Spammy"],
        results=[result],
        cancelled=False,
    )
    # error_count reflects the TRUE total, error_lines is capped.
    assert entry.error_count == n_errors
    assert len(entry.error_lines) == MAX_ERRORS_PER_ENTRY
    # First N preserved (FIFO).
    assert entry.error_lines[0] == "Spammy: e0"
    assert entry.error_lines[-1] == f"Spammy: e{MAX_ERRORS_PER_ENTRY - 1}"
