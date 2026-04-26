"""Run history panel — section E on the Main Dashboard.

Renders the most recent runs persisted by :mod:`scraper.run_history` as a
compact summary table plus a per-row expander for the full breakdown.
Read-only — the engine is the only writer.

The panel renders on every dashboard render rather than via a fragment;
since history only changes once per completed run, polling here would be
overkill. The progress fragment already triggers a full-page rerun on
the run-finished transition (see Iter 5 fix), so the dashboard re-renders
exactly when there's new history to show.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import streamlit as st

from scraper.run_history import RunHistoryEntry, load_entries

#: Maximum number of rows shown on the dashboard. The on-disk file may
#: hold up to ``MAX_ENTRIES`` (Iter 11: 50) but the panel only renders the
#: top slice — the rest is exportable via the JSON file directly.
PANEL_RENDER_LIMIT = 10


def _format_started(dt: datetime) -> str:
    """Render an ISO timestamp as the user's local short form."""
    # Convert to local time for human-friendliness; the persisted value is
    # always timezone-aware UTC so this is always defined.
    local = dt.astimezone() if dt.tzinfo is not None else dt.replace(tzinfo=UTC).astimezone()
    return local.strftime("%Y-%m-%d %H:%M:%S")


def _format_duration(seconds: float) -> str:
    """Compact ``Xm Ys`` / ``Ys`` formatting suited to scrape durations."""
    if seconds < 1:
        return "<1s"
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes, secs = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def _entries_to_summary_frame(entries: list[RunHistoryEntry]) -> pd.DataFrame:
    """Project entries into a small dataframe suitable for ``st.dataframe``."""
    rows = [
        {
            "Started": _format_started(e.started_at),
            "Duration": _format_duration(e.duration_seconds),
            "Sources": len(e.source_names),
            "Items": e.total_items,
            "Pages failed": e.pages_failed,
            "Errors": e.error_count,
            "Layer usage": e.layer_usage_summary(),
            "Outcome": "Cancelled" if e.cancelled else "Completed",
        }
        for e in entries
    ]
    return pd.DataFrame(rows)


def _render_entry_detail(entry: RunHistoryEntry, idx: int) -> None:
    """Per-row expander showing the full breakdown."""
    label = (
        f"#{idx + 1} · {_format_started(entry.started_at)} · "
        f"{entry.total_items} items · {entry.layer_usage_summary()}"
    )
    with st.expander(label):
        cols = st.columns(3)
        cols[0].metric("Items in range", entry.total_items)
        cols[1].metric("Pages scanned", entry.pages_scanned)
        cols[2].metric("Pages failed", entry.pages_failed)

        st.caption(f"Sources: {', '.join(entry.source_names) if entry.source_names else '(none)'}")
        if entry.error_lines:
            st.markdown(f"**Errors ({entry.error_count}):**")
            for line in entry.error_lines:
                st.text(line)
            if entry.error_count > len(entry.error_lines):
                st.caption(
                    f"… {entry.error_count - len(entry.error_lines)} more error(s) "
                    f"truncated to keep the history file small."
                )


def render() -> None:
    """Public entrypoint used by the Main Dashboard."""
    entries = load_entries()
    if not entries:
        st.caption(
            "No completed runs yet. Run the scraper above and this panel will "
            "populate with a one-line summary per run."
        )
        return

    visible = entries[:PANEL_RENDER_LIMIT]
    st.caption(
        f"Last {len(visible)} of {len(entries)} run(s) on disk. "
        f"History is metadata-only — items are not stored here."
    )
    st.dataframe(
        _entries_to_summary_frame(visible),
        use_container_width=True,
        hide_index=True,
    )
    for idx, entry in enumerate(visible):
        _render_entry_detail(entry, idx)


__all__ = ["PANEL_RENDER_LIMIT", "render"]
