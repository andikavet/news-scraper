"""Single-browser session for JS-driven pagination strategies.

Unlike Layer 3's single-shot :class:`scraper.layers.layer3_playwright.Layer3Playwright`,
this module keeps one Playwright page alive across many "pages" of results so
that:

- ``infinite_scroll`` sources can accumulate content via repeated scroll events
  without losing state between pages.
- ``click_next`` sources can click the Next button in the same browser instance
  and let the site's JS update the DOM in place.

Both strategies yield ``(page_num, html)`` tuples. The caller parses each HTML
snapshot with the same ``extract_items`` used by Layer 1, deduping by link on
its own side (see :mod:`scraper.runner`).

Headless-only. Images/fonts/media are route-blocked. The context manager owns
every Playwright resource it creates; exiting it always tears everything down,
even if the producer stops consuming mid-iteration.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger(__name__)

_BLOCKED_RESOURCES = {"image", "media", "font"}
_DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)


class BrowserSessionError(RuntimeError):
    """Raised when the browser session fails in a non-recoverable way."""


@dataclass(frozen=True)
class PageSnapshot:
    """One ``(page_num, html)`` snapshot yielded to the runner."""

    page: int
    html: str
    url: str


def _block_heavy_resources(route, request) -> None:  # type: ignore[no-untyped-def]
    if request.resource_type in _BLOCKED_RESOURCES:
        route.abort()
    else:
        route.continue_()


@contextmanager
def browser_page(
    user_agent: str = _DEFAULT_UA,
    block_resources: bool = True,
) -> Iterator[Page]:
    """Yield a ready-to-navigate Playwright ``Page`` with cleanup guaranteed."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(user_agent=user_agent)
            page = context.new_page()
            if block_resources:
                page.route("**/*", _block_heavy_resources)
            try:
                yield page
            finally:
                context.close()
        finally:
            browser.close()


# --------------------------------------------------------------------------- #
# infinite_scroll
# --------------------------------------------------------------------------- #


def iter_infinite_scroll_pages(
    page: Page,
    url: str,
    start_page: int,
    end_page: int,
    scrolls_per_page: int,
    navigation_timeout: float = 30.0,
    scroll_settle_timeout: float = 5.0,
    should_stop: Callable[[], bool] | None = None,
) -> Iterator[PageSnapshot]:
    """Navigate, then scroll-and-yield ``end_page - start_page + 1`` snapshots.

    Each "page" corresponds to ``scrolls_per_page`` full-page scroll events
    followed by a snapshot of the current DOM. Because infinite-scroll sites
    append to an ever-growing list, the yielded HTML is *cumulative* — the
    runner dedupes by link to count only newly-visible items per page.

    ``should_stop`` is polled before each scroll round so cooperative
    cancellation (UI "Stop" button) is honored promptly.
    """
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=int(navigation_timeout * 1000))
    except PlaywrightTimeoutError as e:
        raise BrowserSessionError(f"infinite_scroll navigation timeout: {e}") from e
    except PlaywrightError as e:
        raise BrowserSessionError(f"infinite_scroll navigation failed: {e}") from e

    # The first snapshot is "page 1" = initial DOM (no scroll yet). Subsequent
    # pages each perform ``scrolls_per_page`` scrolls before snapshotting.
    for page_num in range(start_page, end_page + 1):
        if should_stop is not None and should_stop():
            logger.info("infinite_scroll: stop requested at page %d", page_num)
            return
        if page_num != start_page:
            for _ in range(max(1, scrolls_per_page)):
                if should_stop is not None and should_stop():
                    return
                _scroll_and_wait(page, scroll_settle_timeout)
        yield PageSnapshot(page=page_num, html=page.content(), url=page.url)


def _scroll_and_wait(page: Page, settle_timeout_s: float) -> None:
    before_height = page.evaluate("() => document.body.scrollHeight")
    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    # Wait for network idle OR for body height to grow — whichever comes first.
    try:
        page.wait_for_function(
            "prev => document.body.scrollHeight > prev",
            arg=before_height,
            timeout=int(settle_timeout_s * 1000),
        )
    except PlaywrightTimeoutError:
        # No new content after scroll — legitimate "end of feed"; swallow and
        # let the caller decide whether to keep going.
        logger.debug("scroll produced no new content (height unchanged)")


# --------------------------------------------------------------------------- #
# click_next
# --------------------------------------------------------------------------- #


def iter_click_next_pages(
    page: Page,
    url: str,
    next_button_selector: str | None,
    start_page: int,
    end_page: int,
    navigation_timeout: float = 30.0,
    click_settle_timeout: float = 5.0,
    should_stop: Callable[[], bool] | None = None,
) -> Iterator[PageSnapshot]:
    """Navigate once, then repeatedly click Next and yield the rendered DOM.

    Stops early when:
    - ``end_page`` is reached, or
    - ``next_button_selector`` resolves to no element or a disabled element
      (the site signalled "this is the last page"), or
    - ``should_stop()`` is True (cooperative cancel).
    """
    if not next_button_selector:
        raise BrowserSessionError("click_next requires source.selectors.next_button to be set")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=int(navigation_timeout * 1000))
    except PlaywrightTimeoutError as e:
        raise BrowserSessionError(f"click_next navigation timeout: {e}") from e
    except PlaywrightError as e:
        raise BrowserSessionError(f"click_next navigation failed: {e}") from e

    for page_num in range(start_page, end_page + 1):
        if should_stop is not None and should_stop():
            logger.info("click_next: stop requested at page %d", page_num)
            return
        yield PageSnapshot(page=page_num, html=page.content(), url=page.url)
        if page_num == end_page:
            return
        btn = page.locator(next_button_selector).first
        try:
            if btn.count() == 0:
                logger.info("click_next: no next button after page %d, stopping", page_num)
                return
            if not btn.is_enabled(timeout=1000):
                logger.info("click_next: next button disabled after page %d, stopping", page_num)
                return
            prev_html_len = len(page.content())
            btn.click(timeout=int(click_settle_timeout * 1000))
            # Wait for DOM to change OR for click_settle_timeout to expire. If
            # the site uses full-page navigation ``domcontentloaded`` fires; if
            # it's an in-place swap we detect via HTML-length delta.
            try:
                page.wait_for_function(
                    "prev => document.documentElement.outerHTML.length !== prev",
                    arg=prev_html_len,
                    timeout=int(click_settle_timeout * 1000),
                )
            except PlaywrightTimeoutError:
                logger.debug("click_next: DOM unchanged after click_settle_timeout")
        except PlaywrightTimeoutError as e:
            logger.warning("click_next: click timed out: %s", e)
            return
        except PlaywrightError as e:
            logger.warning("click_next: click failed: %s", e)
            return


__all__ = [
    "BrowserSessionError",
    "PageSnapshot",
    "browser_page",
    "iter_click_next_pages",
    "iter_infinite_scroll_pages",
]
