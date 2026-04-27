"""Pure-Python tests for the Time Range component (Iter 12).

Streamlit-side rendering (radio + four input widgets) is exercised E2E;
here we pin only the date-math helpers since they're the only thing the
engine consumes.
"""

from __future__ import annotations

from datetime import date

from ui.components.time_range import (
    DEFAULT_PRESET,
    QUICK_PRESETS,
    _preset_to_range,
    compute_months_between,
)


def test_quick_presets_match_required_options():
    """The 5 presets the user enumerated must be exactly what we expose."""
    assert QUICK_PRESETS == (
        "This Month",
        "Last Month",
        "This Quarter",
        "Last Quarter",
        "Last Year",
    )


def test_default_preset_is_last_month():
    """User asked for 'Last Month' as the default state on first render."""
    assert DEFAULT_PRESET == "Last Month"


def test_this_month_resolves_to_first_and_last_of_current_month():
    today = date(2026, 4, 15)
    s, e = _preset_to_range("This Month", today)
    assert s == date(2026, 4, 1)
    assert e == date(2026, 4, 30)


def test_last_month_resolves_to_previous_month_full_bounds():
    today = date(2026, 4, 15)
    s, e = _preset_to_range("Last Month", today)
    assert s == date(2026, 3, 1)
    assert e == date(2026, 3, 31)


def test_last_month_january_wraps_to_december_previous_year():
    today = date(2026, 1, 10)
    s, e = _preset_to_range("Last Month", today)
    assert s == date(2025, 12, 1)
    assert e == date(2025, 12, 31)


def test_this_quarter_q2():
    today = date(2026, 5, 7)  # April-June quarter
    s, e = _preset_to_range("This Quarter", today)
    assert s == date(2026, 4, 1)
    assert e == date(2026, 6, 30)


def test_this_quarter_q1_first_month():
    today = date(2026, 1, 1)
    s, e = _preset_to_range("This Quarter", today)
    assert s == date(2026, 1, 1)
    assert e == date(2026, 3, 31)


def test_last_quarter_q1_wraps_to_previous_year_q4():
    today = date(2026, 2, 14)  # Q1 → Last Quarter is 2025 Q4
    s, e = _preset_to_range("Last Quarter", today)
    assert s == date(2025, 10, 1)
    assert e == date(2025, 12, 31)


def test_last_quarter_q3_resolves_to_q2_same_year():
    today = date(2026, 8, 1)  # Q3 → Last Quarter is 2026 Q2
    s, e = _preset_to_range("Last Quarter", today)
    assert s == date(2026, 4, 1)
    assert e == date(2026, 6, 30)


def test_last_year_resolves_to_full_previous_year():
    today = date(2026, 4, 15)
    s, e = _preset_to_range("Last Year", today)
    assert s == date(2025, 1, 1)
    assert e == date(2025, 12, 31)


def test_unknown_preset_returns_none():
    assert _preset_to_range("Custom", date(2026, 1, 1)) is None
    assert _preset_to_range("", date(2026, 1, 1)) is None


def test_compute_months_between_same_month_is_one():
    """Refinement 7: ≥1 so end_page envelope is never zero."""
    today = date(2026, 4, 15)
    assert compute_months_between(date(2026, 4, 1), today=today) == 1


def test_compute_months_between_one_month_back_is_two():
    today = date(2026, 4, 15)
    # Today is April; start is March → 2 months inclusive (Mar, Apr).
    assert compute_months_between(date(2026, 3, 1), today=today) == 2


def test_compute_months_between_full_year_back():
    today = date(2026, 4, 15)
    assert compute_months_between(date(2025, 4, 1), today=today) == 13


def test_compute_months_between_floor_clamps_to_one():
    """Future start dates can't yield a negative envelope."""
    today = date(2026, 1, 1)
    assert compute_months_between(date(2026, 6, 1), today=today) == 1
