"""Time range picker for the Main Dashboard.

Iter 12 redesign: a quick-selector ("This Month" / "Last Month" /
"This Quarter" / "Last Quarter" / "Last Year") drives four
**always-visible** Start Month, Start Year, End Month, End Year inputs.
Clicking a quick selector overwrites the four inputs with the resolved
months; manually editing any of the four inputs updates the selection
without hiding them.

The default quick selector is "Last Month" so first-time users get a
sensible recent window without having to think about months/years.

Pure-Python helpers (``_preset_to_range``, ``months_span``,
``compute_months_between``) are split out so the engine and tests can
exercise the date math without importing Streamlit.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date

import streamlit as st

_MONTH_NAMES = [calendar.month_name[i] for i in range(1, 13)]

#: Required quick selector options (Iter 12).
QUICK_PRESETS: tuple[str, ...] = (
    "This Month",
    "Last Month",
    "This Quarter",
    "Last Quarter",
    "Last Year",
)
DEFAULT_PRESET = "Last Month"


@dataclass(frozen=True)
class TimeRangeSelection:
    start: date
    end: date
    label: str  # e.g. "Last Month" or "Manual: Jan 2026 – Mar 2026"


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    _, last_day = calendar.monthrange(year, month)
    return date(year, month, 1), date(year, month, last_day)


def _quarter_index(month: int) -> int:
    """Return the 0-based quarter index for a month (Jan-Mar=0, etc.)."""
    return (month - 1) // 3


def _preset_to_range(preset: str, today: date) -> tuple[date, date] | None:
    """Resolve a quick-selector label to ``(start, end)`` dates.

    Returns ``None`` for unknown presets so callers can safely fall through
    to the manual inputs.
    """
    if preset == "This Month":
        return _month_bounds(today.year, today.month)
    if preset == "Last Month":
        prev_year = today.year - 1 if today.month == 1 else today.year
        prev_month = 12 if today.month == 1 else today.month - 1
        return _month_bounds(prev_year, prev_month)
    if preset == "This Quarter":
        q = _quarter_index(today.month)
        sm = q * 3 + 1
        em = sm + 2
        return _month_bounds(today.year, sm)[0], _month_bounds(today.year, em)[1]
    if preset == "Last Quarter":
        q = _quarter_index(today.month)
        if q == 0:
            ly, lq = today.year - 1, 3
        else:
            ly, lq = today.year, q - 1
        sm = lq * 3 + 1
        em = sm + 2
        return _month_bounds(ly, sm)[0], _month_bounds(ly, em)[1]
    if preset == "Last Year":
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    return None


def compute_months_between(start: date, today: date | None = None) -> int:
    """Whole-month distance from ``today`` back to ``start`` month, ≥1.

    Used by the source selector for End Page auto-recalc:
    ``end_page = months_between(now, start) × source.avg_page_per_month``.
    Always returns at least 1 so a same-month selection still produces
    a non-zero page envelope.
    """
    today = today if today is not None else date.today()
    months = (today.year - start.year) * 12 + (today.month - start.month) + 1
    return max(1, months)


def _seed_state_from_preset(key_prefix: str, preset: str, today: date) -> None:
    """Push the resolved start/end month+year into session_state."""
    bounds = _preset_to_range(preset, today)
    if bounds is None:
        return
    s, e = bounds
    st.session_state[f"{key_prefix}_sm"] = s.month
    st.session_state[f"{key_prefix}_sy"] = s.year
    st.session_state[f"{key_prefix}_em"] = e.month
    st.session_state[f"{key_prefix}_ey"] = e.year


def render(key_prefix: str = "tr", today: date | None = None) -> TimeRangeSelection:
    """Render the time-range picker and return the selected ``TimeRangeSelection``.

    ``today`` is injectable so tests can pin a known "current date".
    """
    today = today if today is not None else date.today()

    preset_key = f"{key_prefix}_preset"
    sm_key = f"{key_prefix}_sm"
    sy_key = f"{key_prefix}_sy"
    em_key = f"{key_prefix}_em"
    ey_key = f"{key_prefix}_ey"
    last_applied_key = f"{key_prefix}_preset_applied"

    # First render: seed default Last Month into all four inputs.
    if preset_key not in st.session_state:
        st.session_state[preset_key] = DEFAULT_PRESET
        _seed_state_from_preset(key_prefix, DEFAULT_PRESET, today)
        st.session_state[last_applied_key] = DEFAULT_PRESET

    def _on_preset_change() -> None:
        chosen = st.session_state.get(preset_key)
        _seed_state_from_preset(key_prefix, chosen, today)
        st.session_state[last_applied_key] = chosen

    st.radio(
        "Quick selector",
        QUICK_PRESETS,
        horizontal=True,
        key=preset_key,
        on_change=_on_preset_change,
    )

    col1, col2 = st.columns(2)
    with col1:
        st.selectbox(
            "Start month",
            options=list(range(1, 13)),
            format_func=lambda m: _MONTH_NAMES[m - 1],
            key=sm_key,
        )
        st.number_input(
            "Start year",
            min_value=2000,
            max_value=today.year + 1,
            step=1,
            key=sy_key,
        )
    with col2:
        st.selectbox(
            "End month",
            options=list(range(1, 13)),
            format_func=lambda m: _MONTH_NAMES[m - 1],
            key=em_key,
        )
        st.number_input(
            "End year",
            min_value=2000,
            max_value=today.year + 1,
            step=1,
            key=ey_key,
        )

    sm = int(st.session_state[sm_key])
    sy = int(st.session_state[sy_key])
    em = int(st.session_state[em_key])
    ey = int(st.session_state[ey_key])
    start, _ = _month_bounds(sy, sm)
    _, end = _month_bounds(ey, em)
    if start > end:
        st.warning("Start is after End — swap them or pick a different range.")

    # Detect drift: if the four inputs no longer match the last-applied
    # preset's resolved bounds, label the selection as "Manual" so the
    # downstream snapshot reflects the user's actual override.
    last_applied = st.session_state.get(last_applied_key)
    bounds_for_applied = _preset_to_range(last_applied, today) if last_applied else None
    drifted = bounds_for_applied is not None and (
        bounds_for_applied[0] != start or bounds_for_applied[1] != end
    )
    if last_applied and not drifted:
        label = last_applied
        st.caption(f"**{start:%d %b %Y}** → **{end:%d %b %Y}** · preset: {label}")
    else:
        label = f"Manual: {_MONTH_NAMES[sm - 1]} {sy} – {_MONTH_NAMES[em - 1]} {ey}"
        st.caption(
            f"**{start:%d %b %Y}** → **{end:%d %b %Y}** · manual override "
            "(quick selector and inputs disagree)."
        )

    return TimeRangeSelection(start=start, end=end, label=label)


def months_span(sel: TimeRangeSelection) -> int:
    """Inclusive month count — used by the source selector for auto-calc."""
    return max(
        1,
        (sel.end.year - sel.start.year) * 12 + (sel.end.month - sel.start.month) + 1,
    )


__all__ = [
    "DEFAULT_PRESET",
    "QUICK_PRESETS",
    "TimeRangeSelection",
    "compute_months_between",
    "months_span",
    "render",
]
