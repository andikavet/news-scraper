"""Date parsing tests.

Uses a fixed ``reference`` date so relative phrases like ``Kemarin`` /
``5 menit lalu`` produce deterministic results without waiting on the real
wall clock.
"""

from __future__ import annotations

from datetime import date

from scraper.date_parser import format_date, parse_scraped_date

REF = date(2026, 1, 15)


def test_parses_indonesian_short_month():
    assert parse_scraped_date("12 Jan 2026", reference=REF) == date(2026, 1, 12)


def test_parses_indonesian_full_month():
    assert parse_scraped_date("12 Januari 2026", reference=REF) == date(2026, 1, 12)


def test_parses_english_short_month():
    assert parse_scraped_date("Jan 12, 2026", reference=REF) == date(2026, 1, 12)


def test_parses_relative_kemarin():
    assert parse_scraped_date("Kemarin", reference=REF) == date(2026, 1, 14)


def test_parses_relative_minutes_ago_indonesian():
    # 5 menit lalu on ref → same day
    assert parse_scraped_date("5 menit lalu", reference=REF) == REF


def test_parses_relative_hours_ago():
    assert parse_scraped_date("2 jam yang lalu", reference=REF) == REF


def test_parses_numeric_ddmmyyyy():
    # dateparser defaults to day-first only when the language is ambiguous;
    # 12/01/2026 under id+en will resolve via id's day-first convention.
    assert parse_scraped_date("12/01/2026", reference=REF) == date(2026, 1, 12)


def test_empty_returns_none():
    assert parse_scraped_date("", reference=REF) is None
    assert parse_scraped_date("   ", reference=REF) is None


def test_garbage_returns_none():
    assert parse_scraped_date("not a date at all", reference=REF) is None


def test_format_date_ddmmyyyy():
    assert format_date(date(2026, 1, 9)) == "09-01-2026"


def test_format_date_none_is_empty():
    assert format_date(None) == ""
