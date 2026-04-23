"""Pagination strategies for the scraping engine.

A pagination strategy knows how to turn a configured source's ``url_template``
+ current page number into either:
- A concrete URL to fetch (for ``url_params``), or
- A driver-level operation (scroll / click next) — those strategies are stubs
  here and fully implemented in Iter 7 alongside the Playwright layers.

Only ``url_params`` is functional at this iteration because Layer 1 cannot
drive a browser.
"""

from __future__ import annotations

from dataclasses import dataclass

from config import ScrapeSource


class PaginationNotSupportedError(RuntimeError):
    """Raised when a pagination strategy requires a layer that's not wired yet.

    Iter 7 wires ``infinite_scroll`` and ``click_next`` via Playwright.
    """


@dataclass(frozen=True)
class PageRequest:
    """One unit of work handed to a ``Layer.fetch()``."""

    page: int
    url: str


def url_for_page(source: ScrapeSource, page: int) -> str:
    """Resolve ``source.url_template`` for ``page`` using ``{page}`` substitution.

    No pagination_type check here — the template substitution is identical for
    all strategies; callers enforce the layer/strategy compatibility.
    """
    template = source.url_template
    if "{page}" not in template:
        # Single-page source: still useful when the site has no pagination.
        return template
    return template.replace("{page}", str(page))


def iter_page_requests(source: ScrapeSource, start_page: int, end_page: int):
    """Yield ``PageRequest``s for ``url_params`` sources in ``[start_page, end_page]``.

    Raises ``PaginationNotSupportedError`` for strategies that require a
    browser. Those are handled by the Playwright runner in Iter 7.
    """
    if source.pagination_type != "url_params":
        raise PaginationNotSupportedError(
            f"Pagination type {source.pagination_type!r} needs a Playwright layer "
            "(Iteration 7). Layer 1 only supports 'url_params'."
        )
    if start_page > end_page:
        return
    for page in range(start_page, end_page + 1):
        yield PageRequest(page=page, url=url_for_page(source, page))


__all__ = [
    "PageRequest",
    "PaginationNotSupportedError",
    "iter_page_requests",
    "url_for_page",
]
