"""CSS-selector extraction helpers.

All selector application goes through this module so every layer parses
HTML the same way and so the Settings-page "Test Selector" tool uses the
exact same code path as production scraping.

Two parser backends are offered:

- ``extract_items`` — BeautifulSoup + lxml (Layer 1 and Layer 3). Robust,
  well-understood, slightly slower.
- ``extract_items_selectolax`` — Modest-C-based selectolax (Layer 2). Roughly
  5-10x faster on large documents and more tolerant of malformed HTML.

Both return the same ``list[RawScrapeHit]`` on well-formed input so the
fallback cascade (Iter 8) can swap parsers without changing downstream logic.
"""

from __future__ import annotations

from typing import Literal

from bs4 import BeautifulSoup, Tag
from selectolax.parser import HTMLParser, Node

from config import ScraperSelectors
from scraper.models import RawScrapeHit

ParserName = Literal["bs4", "selectolax"]


# --------------------------------------------------------------------------- #
# BeautifulSoup backend
# --------------------------------------------------------------------------- #


def _bs4_text(node: Tag | None) -> str:
    if node is None:
        return ""
    return node.get_text(strip=True)


def _bs4_attr(node: Tag | None, attr: str) -> str:
    if node is None:
        return ""
    val = node.get(attr)
    if isinstance(val, list):
        return val[0] if val else ""
    return val or ""


def _bs4_resolve_link(node: Tag | None) -> str:
    """Return the href of ``node``, or of the nearest descendant <a>."""
    if node is None:
        return ""
    if node.name == "a":
        return _bs4_attr(node, "href")
    inner_a = node.select_one("a")
    if inner_a is not None:
        return _bs4_attr(inner_a, "href")
    return ""


def extract_items(html: str, selectors: ScraperSelectors) -> list[RawScrapeHit]:
    """Apply ``selectors`` to ``html`` via BeautifulSoup + lxml.

    Missing title or link causes the hit to be skipped — partial rows are
    worse than no row for downstream categorization and date parsing.
    """
    soup = BeautifulSoup(html, "lxml")
    containers = soup.select(selectors.container)

    hits: list[RawScrapeHit] = []
    for node in containers:
        title = _bs4_text(node.select_one(selectors.title))
        link = _bs4_resolve_link(node.select_one(selectors.link))
        date_raw = _bs4_text(node.select_one(selectors.date))
        if not title or not link:
            continue
        hits.append(RawScrapeHit(title=title, link=link, date_raw=date_raw))
    return hits


# --------------------------------------------------------------------------- #
# selectolax backend (Layer 2)
# --------------------------------------------------------------------------- #


def _slx_text(node: Node | None) -> str:
    if node is None:
        return ""
    # ``strip=True`` in selectolax's text() collapses leading/trailing whitespace
    # but keeps internal whitespace — matches BS4's ``get_text(strip=True)``.
    return node.text(strip=True)


def _slx_attr(node: Node | None, attr: str) -> str:
    if node is None:
        return ""
    val = node.attributes.get(attr)
    return val or ""


def _slx_resolve_link(node: Node | None) -> str:
    """Return the href of ``node``, or of the nearest descendant <a>."""
    if node is None:
        return ""
    if node.tag == "a":
        return _slx_attr(node, "href")
    inner_a = node.css_first("a")
    if inner_a is not None:
        return _slx_attr(inner_a, "href")
    return ""


def extract_items_selectolax(html: str, selectors: ScraperSelectors) -> list[RawScrapeHit]:
    """Apply ``selectors`` to ``html`` via selectolax.

    Contract is identical to :func:`extract_items` — same input, same output
    on well-formed HTML. The difference is performance and tolerance to
    malformed markup, which makes this a useful Layer 2 alternative when
    Layer 1's lxml backend rejects a broken page.
    """
    tree = HTMLParser(html)
    containers = tree.css(selectors.container)

    hits: list[RawScrapeHit] = []
    for node in containers:
        title = _slx_text(node.css_first(selectors.title))
        link = _slx_resolve_link(node.css_first(selectors.link))
        date_raw = _slx_text(node.css_first(selectors.date))
        if not title or not link:
            continue
        hits.append(RawScrapeHit(title=title, link=link, date_raw=date_raw))
    return hits


# --------------------------------------------------------------------------- #
# Dispatcher
# --------------------------------------------------------------------------- #


def parse_for(parser_name: str, html: str, selectors: ScraperSelectors) -> list[RawScrapeHit]:
    """Dispatch to the parser backend named ``parser_name``.

    Unknown names fall back to the BS4 backend so a layer that forgets to
    declare ``parser_name`` still parses correctly.
    """
    if parser_name == "selectolax":
        return extract_items_selectolax(html, selectors)
    return extract_items(html, selectors)


__all__ = [
    "ParserName",
    "extract_items",
    "extract_items_selectolax",
    "parse_for",
]
