"""UI-side run-history panel smoke tests.

We don't try to render Streamlit components in tests (that needs the
live server); instead we exercise the pure helpers in
``ui.components.run_history_panel`` so the formatting logic is pinned.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from scraper.run_history import RunHistoryEntry
from ui.components.run_history_panel import (
    PANEL_RENDER_LIMIT,
    _entries_to_summary_frame,
    _format_duration,
    _format_started,
)


def test_format_duration_handles_sub_second():
    assert _format_duration(0.0) == "<1s"
    assert _format_duration(0.5) == "<1s"


def test_format_duration_seconds_bucket():
    assert _format_duration(1) == "1s"
    assert _format_duration(45) == "45s"
    assert _format_duration(59.9) == "60s"


def test_format_duration_minutes_bucket():
    assert _format_duration(60) == "1m 0s"
    assert _format_duration(75) == "1m 15s"
    assert _format_duration(3599) == "59m 59s"


def test_format_duration_hours_bucket():
    assert _format_duration(3600) == "1h 0m"
    assert _format_duration(7325) == "2h 2m"


def test_format_started_renders_iso_timestamp():
    dt = datetime(2026, 4, 23, 13, 48, tzinfo=UTC)
    rendered = _format_started(dt)
    # Local-time conversion makes the exact string machine-dependent;
    # pin only the structure.
    assert len(rendered) == 19
    assert rendered[4] == "-" and rendered[7] == "-"
    assert rendered[10] == " "
    assert rendered[13] == ":" and rendered[16] == ":"


def test_entries_to_summary_frame_columns():
    e = RunHistoryEntry(
        started_at=datetime(2026, 4, 23, 9, 0, tzinfo=UTC),
        finished_at=datetime(2026, 4, 23, 9, 0, 15, tzinfo=UTC),
        source_names=["Alpha", "Beta"],
        total_items=12,
        pages_scanned=8,
        pages_failed=1,
        layer_usage={1: 6, 2: 2},
        cancelled=False,
        error_count=2,
    )
    df = _entries_to_summary_frame([e])
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == [
        "Started",
        "Duration",
        "Sources",
        "Items",
        "Pages failed",
        "Errors",
        "Layer usage",
        "Outcome",
    ]
    [row] = df.to_dict(orient="records")
    assert row["Sources"] == 2
    assert row["Items"] == 12
    assert row["Pages failed"] == 1
    assert row["Errors"] == 2
    assert row["Layer usage"] == "L1=6, L2=2"
    assert row["Outcome"] == "Completed"


def test_entries_to_summary_frame_marks_cancelled_runs():
    e = RunHistoryEntry(
        started_at=datetime(2026, 4, 23, 9, 0, tzinfo=UTC),
        finished_at=datetime(2026, 4, 23, 9, 0, 5, tzinfo=UTC),
        source_names=["Alpha"],
        cancelled=True,
    )
    [row] = _entries_to_summary_frame([e]).to_dict(orient="records")
    assert row["Outcome"] == "Cancelled"


def test_panel_render_limit_is_a_subset_of_storage():
    """The dashboard shows fewer rows than the on-disk cap.

    Pinning so the panel never accidentally tries to render all 50 rows
    on every dashboard tick — that's a noticeable scroll for a side panel.
    """
    from scraper.run_history import MAX_ENTRIES

    assert PANEL_RENDER_LIMIT < MAX_ENTRIES
