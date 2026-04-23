"""Abstract ``Layer`` interface and shared exceptions for the scraping engine.

The 4-layer fallback strategy (PRD §4.1) works by trying layers in ascending
order of complexity. Each concrete layer implements ``fetch()`` returning the
raw page bytes/HTML, and the caller (``scraper.runner``) is responsible for
parsing + retry + sleep.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ScrapeError(Exception):
    """Raised by a layer when the fetch fails in a retryable way.

    Non-retryable failures (e.g. 404 on the URL template) should still raise
    ``ScrapeError`` — the runner decides whether to fall back to the next
    layer based on ``enabled_layers`` from config.
    """


@dataclass(frozen=True)
class FetchResult:
    """What every layer returns from ``fetch()``.

    ``html`` is unicode-decoded; ``status_code`` is ``None`` for layers that
    don't have an HTTP status (e.g. in-browser Playwright navigation can
    succeed without a classical status code on same-page routing).
    """

    url: str
    html: str
    status_code: int | None


class Layer(Protocol):
    """Interface implemented by every scraping layer."""

    layer_number: int
    name: str

    def fetch(self, url: str, timeout: float = 20.0) -> FetchResult: ...


__all__ = ["FetchResult", "Layer", "ScrapeError"]
