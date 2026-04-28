"""Abstract ``Layer`` interface and shared exceptions for the scraping engine.

The 4-layer fallback strategy (PRD §4.1) works by trying layers in ascending
order of complexity. Each concrete layer implements ``fetch()`` returning the
raw page bytes/HTML, and the caller (``scraper.runner``) is responsible for
parsing + retry + sleep.

Iter 14: :meth:`Layer.fetch` accepts an optional ``wait_selector`` hint so
JS-rendered layers (3 & 4) can block on the container becoming attached to
the DOM before returning. HTTP-only layers (1 & 2) ignore the hint — the
response body is already fully materialised by the time the layer returns.
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
    """Interface implemented by every scraping layer.

    ``wait_selector`` is an optional CSS selector the layer should wait
    for before reading the page's HTML. JS-rendered layers use it to
    block until the listing is attached to the DOM instead of relying on
    a generic ``networkidle`` state that never settles on ad-heavy
    news sites. HTTP-only layers ignore the hint.
    """

    layer_number: int
    name: str

    def fetch(
        self,
        url: str,
        timeout: float = 20.0,
        *,
        wait_selector: str | None = None,
    ) -> FetchResult: ...


__all__ = ["FetchResult", "Layer", "ScrapeError"]
