"""Core data structures shared across the scraper package.

Kept free of Streamlit and I/O imports so every layer can consume them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class NewsItem:
    """One scraped article row, post-normalization.

    ``date_parsed`` is the authoritative machine-comparable date used by the
    early-stopping logic; ``date_raw`` is kept for debugging / display.
    """

    title: str
    link: str
    date_raw: str
    date_parsed: date | None
    source: str
    page: int


@dataclass
class RawScrapeHit:
    """What a layer returns per container before date parsing happens."""

    title: str
    link: str
    date_raw: str


@dataclass
class SelectorCheck:
    """Per-selector outcome of a Test Selector run.

    ``matched`` is False when the selector returned no value (or, for
    ``container``, no nodes); ``samples`` shows up to a few extracted
    values so the user can see what the selector actually pulled.
    """

    name: str  # "container" / "title" / "link" / "date"
    selector: str
    matched: bool
    samples: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class TestSelectorResult:
    """Output of the Settings-page 'Test Selector' tool.

    ``items`` is populated when the fetch succeeded, regardless of whether the
    selectors matched anything — zero-length results are a valid failure mode
    that the UI surfaces differently from network errors.

    Iter 12 adds per-selector ``checks`` so the UI can differentiate between
    container/title/link/date pass/fail rather than just showing one combined
    "0 items matched" warning.
    """

    ok: bool
    url: str
    status_code: int | None
    layer: str
    items: list[RawScrapeHit] = field(default_factory=list)
    error: str | None = None
    checks: list[SelectorCheck] = field(default_factory=list)


__all__ = ["NewsItem", "RawScrapeHit", "SelectorCheck", "TestSelectorResult"]
