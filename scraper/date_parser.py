"""Date parsing for scraped article timestamps.

Wraps ``dateparser`` with the Indonesian + English locales the PRD targets and
pins the result to ``datetime.date`` (time-of-day is dropped — the early-stop
and filtering logic only compare calendar days).

Indonesian sites commonly use:
- absolute: ``12 Jan 2026``, ``12 Januari 2026``, ``12/01/2026``
- relative: ``5 menit lalu``, ``2 jam yang lalu``, ``Kemarin``, ``Hari ini``

English sites commonly use:
- absolute: ``Jan 12, 2026``, ``12 January 2026``, ``2026-01-12``
- relative: ``5 minutes ago``, ``Yesterday``, ``Today``

All relative dates are resolved relative to ``today()`` at parse time unless a
``reference`` date is injected (tests do this to keep results deterministic).
"""

from __future__ import annotations

from datetime import date, datetime

import dateparser

_LANGUAGES: list[str] = ["id", "en"]
_OUTPUT_FORMAT = "%d-%m-%Y"


def parse_scraped_date(raw: str, reference: date | None = None) -> date | None:
    """Parse ``raw`` into a ``date`` or ``None`` if unparseable.

    Relative phrases (``menit lalu`` / ``Kemarin`` / ``minutes ago``) are
    resolved against ``reference`` if provided, otherwise against today.
    """
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None

    settings: dict[str, object] = {
        "PREFER_DAY_OF_MONTH": "first",
        "RETURN_AS_TIMEZONE_AWARE": False,
        # Indonesian + European convention is day-first; without this, purely
        # numeric strings like ``12/01/2026`` get interpreted as 2026-12-01.
        "DATE_ORDER": "DMY",
    }
    if reference is not None:
        # Anchor relative phrases at noon so ``5 menit lalu`` / ``2 jam yang
        # lalu`` don't underflow the calendar day by landing in the previous
        # night.
        settings["RELATIVE_BASE"] = datetime.combine(reference, datetime.min.time()).replace(
            hour=12
        )

    parsed = dateparser.parse(text, languages=_LANGUAGES, settings=settings)
    if parsed is None:
        return None
    return parsed.date()


def format_date(d: date | None) -> str:
    """Render a ``date`` as ``DD-MM-YYYY``; empty string when ``d`` is None."""
    if d is None:
        return ""
    return d.strftime(_OUTPUT_FORMAT)


__all__ = ["format_date", "parse_scraped_date"]
