"""Run history panel — section E on the Main Dashboard.

Renders the most recent runs persisted by :mod:`scraper.run_history` as a
compact summary table plus a per-row expander for the full breakdown.
Read-only with one mutating affordance — the Iter 13 **Clear History**
button (two-step confirmation, inline success banner) — surfaced
alongside the panel header.

The panel renders on every dashboard render rather than via a fragment;
since history only changes once per completed run (or a manual clear),
polling here would be overkill. The progress fragment already triggers
a full-page rerun on the run-finished transition (see Iter 5 fix), so
the dashboard re-renders exactly when there's new history to show.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import streamlit as st

from scraper.run_history import RunHistoryEntry, clear_entries, load_entries

#: Maximum number of rows shown on the dashboard. The on-disk file may
#: hold up to ``MAX_ENTRIES`` (Iter 11: 50) but the panel only renders the
#: top slice — the rest is exportable via the JSON file directly.
PANEL_RENDER_LIMIT = 10

#: Session-state key for the two-step Clear-History confirmation flag.
_CLEAR_CONFIRM_KEY = "run_history_clear_confirm"

#: One-shot inline status banner that survives an ``st.rerun()``. Stored
#: as ``(level, message)`` and consumed once on the next render. Mirrors
#: the ``_flash`` / ``_consume_status`` pattern from the Iter 12 forms so
#: the success message persists across the rerun triggered by the wipe.
_STATUS_KEY = "run_history_panel_status"


def _flash(level: str, message: str) -> None:
    st.session_state[_STATUS_KEY] = (level, message)


def _consume_status() -> None:
    pending = st.session_state.pop(_STATUS_KEY, None)
    if pending is None:
        return
    level, message = pending
    if level == "success":
        st.success(message)
    elif level == "error":
        st.error(message)
    elif level == "warning":
        st.warning(message)
    else:
        st.info(message)


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


def _render_clear_button(entry_count: int) -> None:
    """Two-step Clear History button (mirrors Iter 12's delete pattern).

    Sequence:
        1. First click → flips ``_CLEAR_CONFIRM_KEY``, relabels the button
           to ``⚠️ Click again to confirm clear``, and shows an inline
           warning banner. No mutation yet.
        2. Second click within the same session → calls
           :func:`scraper.run_history.clear_entries`, stages a success
           flash that survives the ``st.rerun()``, and drops the flag.

    Idempotent: clicking when the history is already empty wipes nothing
    and surfaces a neutral info banner. The button is disabled in that
    case so the user gets the visual hint anyway.
    """
    pending = bool(st.session_state.get(_CLEAR_CONFIRM_KEY))
    label = (
        "⚠️ Click again to confirm clear"
        if pending
        else f"Clear history ({entry_count})"
    )
    clicked = st.button(
        label,
        key="run_history_clear_btn",
        type="secondary",
        disabled=entry_count == 0,
        help=(
            "Permanently delete every entry from the run-history log on disk. "
            "This does not affect the categorized items or any exported files."
        ),
    )
    if not clicked:
        return
    if not pending:
        st.session_state[_CLEAR_CONFIRM_KEY] = True
        st.warning(
            f"Clear all {entry_count} run-history entr"
            f"{'y' if entry_count == 1 else 'ies'}? "
            "Click the button again to confirm."
        )
        return
    removed = clear_entries()
    st.session_state.pop(_CLEAR_CONFIRM_KEY, None)
    _flash(
        "success",
        f"Cleared {removed} run-history entr{'y' if removed == 1 else 'ies'}.",
    )
    st.rerun()


def render() -> None:
    """Public entrypoint used by the Main Dashboard."""
    _consume_status()
    entries = load_entries()

    header_col, button_col = st.columns([1, 0.28])
    with header_col:
        if entries:
            st.caption(
                f"Last {min(len(entries), PANEL_RENDER_LIMIT)} of {len(entries)} run(s) "
                f"on disk. History is metadata-only — items are not stored here."
            )
        else:
            st.caption(
                "No completed runs yet. Run the scraper above and this panel will "
                "populate with a one-line summary per run."
            )
    with button_col:
        _render_clear_button(len(entries))

    if not entries:
        return

    visible = entries[:PANEL_RENDER_LIMIT]
    st.dataframe(
        _entries_to_summary_frame(visible),
        use_container_width=True,
        hide_index=True,
    )
    for idx, entry in enumerate(visible):
        _render_entry_detail(entry, idx)


__all__ = ["PANEL_RENDER_LIMIT", "render"]
