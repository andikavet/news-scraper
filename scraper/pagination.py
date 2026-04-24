"""Pagination strategies for the scraping engine.

A pagination strategy knows how to turn a configured source's ``url_template``
+ current page number into either:
- A concrete URL to fetch (for ``url_params``), or
- A driver-level operation (scroll / click next) — these strategies are
  driven by :mod:`scraper.playwright_session` rather than being expressed
  as page requests because they require persistent browser state.
"""

from __future__ import annotations

from dataclasses import dataclass

from config import ScrapeSource


class PaginationNotSupportedError(RuntimeError):
    """Raised when ``iter_page_requests`` is asked to handle a non-URL strategy.

    JS-driven strategies (``infinite_scroll`` / ``click_next``) are handled
    by the browser runner, not by URL iteration. See
    :func:`scraper.runner.run_browser_source`.
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


def needs_browser(source: ScrapeSource) -> bool:
    """Return True when the source requires a live browser to paginate.

    ``infinite_scroll`` and ``click_next`` need persistent JS/DOM state
    across pages; ``url_params`` is plain HTTP and can stay on Layer 1.
    """
    return source.pagination_type in ("infinite_scroll", "click_next")


def iter_page_requests(source: ScrapeSource, start_page: int, end_page: int):
    """Yield ``PageRequest``s for ``url_params`` sources in ``[start_page, end_page]``.

    Raises ``PaginationNotSupportedError`` for strategies that require a
    browser. Those are handled by :func:`scraper.runner.run_browser_source`.
    """
    if source.pagination_type != "url_params":
        raise PaginationNotSupportedError(
            f"Pagination type {source.pagination_type!r} requires a browser session; "
            "use scraper.runner.run_browser_source instead."
        )
    if start_page > end_page:
        return
    for page in range(start_page, end_page + 1):
        yield PageRequest(page=page, url=url_for_page(source, page))


__all__ = [
    "PageRequest",
    "PaginationNotSupportedError",
    "iter_page_requests",
    "needs_browser",
    "url_for_page",
]
