"""CSS-selector extraction helpers.

All selector application goes through this module so every layer parses
HTML the same way and so the Settings-page "Test Selector" tool uses the
exact same code path as production scraping.
"""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag

from config import ScraperSelectors
from scraper.models import RawScrapeHit


def _text(node: Tag | None) -> str:
    if node is None:
        return ""
    return node.get_text(strip=True)


def _attr(node: Tag | None, attr: str) -> str:
    if node is None:
        return ""
    val = node.get(attr)
    if isinstance(val, list):
        return val[0] if val else ""
    return val or ""


def _resolve_link(node: Tag | None) -> str:
    """Return the href of ``node``, or of the nearest descendant <a>."""
    if node is None:
        return ""
    if node.name == "a":
        return _attr(node, "href")
    inner_a = node.select_one("a")
    if inner_a is not None:
        return _attr(inner_a, "href")
    return ""


def extract_items(html: str, selectors: ScraperSelectors) -> list[RawScrapeHit]:
    """Apply ``selectors`` to ``html`` and return raw hits.

    The selectors are relative to the ``container``. Missing title or link
    causes the hit to be skipped — partial rows are worse than no row for
    downstream categorization and date parsing.
    """
    soup = BeautifulSoup(html, "lxml")
    containers = soup.select(selectors.container)

    hits: list[RawScrapeHit] = []
    for node in containers:
        title = _text(node.select_one(selectors.title))
        link = _resolve_link(node.select_one(selectors.link))
        date_raw = _text(node.select_one(selectors.date))
        if not title or not link:
            continue
        hits.append(RawScrapeHit(title=title, link=link, date_raw=date_raw))
    return hits


__all__ = ["extract_items"]
