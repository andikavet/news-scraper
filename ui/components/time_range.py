"""Time range picker for the Main Dashboard.

Presents quick-selector buttons ("This Month", "Last Month", "YTD",
"This Year") + a manual "Custom" mode with start/end month+year
dropdowns. Returns ``(start_date, end_date)`` so the engine can filter
on a proper range.

Kept thin — no scraping logic, just widget plumbing.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date

import streamlit as st

_MONTH_NAMES = [calendar.month_name[i] for i in range(1, 13)]
_QUICK_PRESETS = ["This Month", "Last Month", "Year to Date", "This Year", "Custom"]


@dataclass(frozen=True)
class TimeRangeSelection:
    start: date
    end: date
    label: str  # e.g. "This Month" or "Custom: Jan 2026 – Mar 2026"


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    _, last_day = calendar.monthrange(year, month)
    return date(year, month, 1), date(year, month, last_day)


def _preset_to_range(preset: str, today: date) -> tuple[date, date] | None:
    if preset == "This Month":
        return _month_bounds(today.year, today.month)
    if preset == "Last Month":
        prev_year = today.year - 1 if today.month == 1 else today.year
        prev_month = 12 if today.month == 1 else today.month - 1
        return _month_bounds(prev_year, prev_month)
    if preset == "Year to Date":
        return date(today.year, 1, 1), today
    if preset == "This Year":
        return date(today.year, 1, 1), date(today.year, 12, 31)
    return None  # Custom


def render(key_prefix: str = "tr", today: date | None = None) -> TimeRangeSelection:
    """Render the time-range picker and return the selected ``TimeRangeSelection``.

    ``today`` is injectable so tests can pin a known "current date".
    """
    today = today if today is not None else date.today()
    preset = st.radio(
        "Quick selector",
        _QUICK_PRESETS,
        horizontal=True,
        key=f"{key_prefix}_preset",
    )

    if preset != "Custom":
        bounds = _preset_to_range(preset, today)
        assert bounds is not None  # guarded by the preset list
        start, end = bounds
        st.caption(f"**{start:%d %b %Y}** → **{end:%d %b %Y}**")
        return TimeRangeSelection(start=start, end=end, label=preset)

    col1, col2 = st.columns(2)
    with col1:
        sm = st.selectbox(
            "Start month",
            options=list(range(1, 13)),
            format_func=lambda m: _MONTH_NAMES[m - 1],
            index=today.month - 1,
            key=f"{key_prefix}_sm",
        )
        sy = st.number_input(
            "Start year",
            min_value=2000,
            max_value=today.year + 1,
            value=today.year,
            step=1,
            key=f"{key_prefix}_sy",
        )
    with col2:
        em = st.selectbox(
            "End month",
            options=list(range(1, 13)),
            format_func=lambda m: _MONTH_NAMES[m - 1],
            index=today.month - 1,
            key=f"{key_prefix}_em",
        )
        ey = st.number_input(
            "End year",
            min_value=2000,
            max_value=today.year + 1,
            value=today.year,
            step=1,
            key=f"{key_prefix}_ey",
        )

    start, _ = _month_bounds(int(sy), int(sm))
    _, end = _month_bounds(int(ey), int(em))
    if start > end:
        st.warning("Start is after End — swap them or pick a different range.")
    label = f"Custom: {_MONTH_NAMES[int(sm) - 1]} {int(sy)} – {_MONTH_NAMES[int(em) - 1]} {int(ey)}"
    return TimeRangeSelection(start=start, end=end, label=label)


def months_span(sel: TimeRangeSelection) -> int:
    """Inclusive month count — used by the source selector for auto-calc."""
    return max(
        1,
        (sel.end.year - sel.start.year) * 12 + (sel.end.month - sel.start.month) + 1,
    )


__all__ = ["TimeRangeSelection", "months_span", "render"]
