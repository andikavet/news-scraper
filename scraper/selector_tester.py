"""The 'Test Selector' tool wired for the Settings page.

Runs a single Layer 1 fetch against one URL and applies the user-provided
selectors. Returns a ``TestSelectorResult`` that the UI renders as either a
preview table or an error banner.

This deliberately stays on Layer 1 only — higher layers spin up Playwright,
which would be a terrible UX for a "click and see what you got" button.
Iteration 7 can add a "Test Selector (Playwright)" toggle if needed.

Iter 12 adds per-selector diagnostics: instead of a single "fetched + N
items" report, the result includes one :class:`SelectorCheck` per selector
(container / title / link / date) so the UI can flag exactly which
selector failed and show samples from the ones that worked.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from config import ScraperSelectors
from scraper.layers.base import ScrapeError
from scraper.layers.layer1_httpx import Layer1Httpx
from scraper.models import RawScrapeHit, SelectorCheck, TestSelectorResult
from scraper.parsers import _bs4_resolve_link, _bs4_text

#: How many extracted values to keep per selector for the UI preview.
#: Three is enough to demonstrate the selector works without flooding the UI.
_MAX_SAMPLES = 3


def _build_checks(
    html: str, selectors: ScraperSelectors
) -> tuple[list[SelectorCheck], list[RawScrapeHit]]:
    """Run each selector independently and return per-selector outcomes + hits.

    Container is checked first against the whole document; title/link/date
    are checked against the matched containers. A failed container check
    short-circuits the rest with explicit "skipped" markers since you
    can't meaningfully check sub-selectors without containers to look in.
    """
    soup = BeautifulSoup(html, "lxml")
    containers = soup.select(selectors.container) if selectors.container else []

    container_check = SelectorCheck(
        name="container",
        selector=selectors.container,
        matched=len(containers) > 0,
        samples=[f"{len(containers)} container(s) found"] if containers else [],
        error=None
        if containers
        else f"Container selector '{selectors.container}' matched zero nodes.",
    )

    if not containers:
        # Without containers there's nothing to scope sub-selectors against.
        # Mark each as "skipped" with the same selector text so the UI can
        # still show the user what was tried.
        skipped = [
            SelectorCheck(
                name=name,
                selector=sel,
                matched=False,
                error=(
                    f"Skipped: {name} selector '{sel}' could not be tested because "
                    f"the container selector matched zero nodes."
                ),
            )
            for name, sel in (
                ("title", selectors.title),
                ("link", selectors.link),
                ("date", selectors.date),
            )
        ]
        return [container_check, *skipped], []

    title_samples: list[str] = []
    link_samples: list[str] = []
    date_samples: list[str] = []
    title_misses = 0
    link_misses = 0
    date_misses = 0
    hits: list[RawScrapeHit] = []

    for node in containers:
        title = _bs4_text(node.select_one(selectors.title)) if selectors.title else ""
        link = _bs4_resolve_link(node.select_one(selectors.link)) if selectors.link else ""
        date_raw = _bs4_text(node.select_one(selectors.date)) if selectors.date else ""

        if not title:
            title_misses += 1
        elif len(title_samples) < _MAX_SAMPLES:
            title_samples.append(title)
        if not link:
            link_misses += 1
        elif len(link_samples) < _MAX_SAMPLES:
            link_samples.append(link)
        if not date_raw:
            date_misses += 1
        elif len(date_samples) < _MAX_SAMPLES:
            date_samples.append(date_raw)

        if title and link:
            hits.append(RawScrapeHit(title=title, link=link, date_raw=date_raw))

    def _check(name: str, selector: str, samples: list[str], misses: int) -> SelectorCheck:
        matched = len(samples) > 0
        if matched:
            error = None
            if misses:
                error = (
                    f"{name.capitalize()} selector '{selector}' missing on "
                    f"{misses} of {len(containers)} container(s)."
                )
            return SelectorCheck(
                name=name, selector=selector, matched=True, samples=samples, error=error
            )
        return SelectorCheck(
            name=name,
            selector=selector,
            matched=False,
            error=f"{name.capitalize()} selector '{selector}' not found in any of {len(containers)} container(s).",
        )

    return (
        [
            container_check,
            _check("title", selectors.title, title_samples, title_misses),
            _check("link", selectors.link, link_samples, link_misses),
            _check("date", selectors.date, date_samples, date_misses),
        ],
        hits,
    )


def run_selector_test(url: str, selectors: ScraperSelectors) -> TestSelectorResult:
    """Fetch ``url`` once via Layer 1 and return whatever the selectors found."""
    layer = Layer1Httpx()
    try:
        fetched = layer.fetch(url)
    except ScrapeError as e:
        return TestSelectorResult(
            ok=False,
            url=url,
            status_code=None,
            layer=layer.name,
            error=str(e),
        )

    checks, hits = _build_checks(fetched.html, selectors)
    return TestSelectorResult(
        ok=True,
        url=fetched.url,
        status_code=fetched.status_code,
        layer=layer.name,
        items=hits,
        checks=checks,
    )


__all__ = ["run_selector_test"]
