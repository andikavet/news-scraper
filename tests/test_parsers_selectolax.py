"""Parity tests for the selectolax parser backend (Layer 2).

``extract_items`` (BS4+lxml) and ``extract_items_selectolax`` MUST return
the same ``RawScrapeHit``s on well-formed HTML — this is the core
invariant that makes the parsers interchangeable when the orchestrator
falls back from Layer 1 to Layer 2. A divergence would leak into the
categorization pipeline and silently change results.

Separately we cover selectolax's differentiator — resilience to malformed
markup — so the case where Layer 2 gives us *more* hits than Layer 1 on
broken HTML is also pinned down.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config import ScraperSelectors
from scraper.parsers import extract_items, extract_items_selectolax, parse_for

_FIXTURE = Path(__file__).parent / "fixtures" / "portalx_listing.html"

_SEL = ScraperSelectors(
    container="li.article-item",
    title="h2 > a",
    link="h2 > a",
    date=".date-time",
)


@pytest.fixture
def html() -> str:
    return _FIXTURE.read_text(encoding="utf-8")


def test_selectolax_parity_with_bs4(html: str) -> None:
    """On well-formed HTML, both backends must yield identical hits."""
    bs4_hits = extract_items(html, _SEL)
    slx_hits = extract_items_selectolax(html, _SEL)
    # Same number, order, content.
    assert len(bs4_hits) == len(slx_hits) == 3
    for a, b in zip(bs4_hits, slx_hits, strict=True):
        assert a.title == b.title
        assert a.link == b.link
        assert a.date_raw == b.date_raw


def test_selectolax_skips_partial_rows() -> None:
    """Same row-skipping contract as the BS4 extractor."""
    html = """
    <ul>
      <li class='x'><h2><a href='/a'>Title</a></h2><span class='d'>today</span></li>
      <li class='x'><h2></h2><span class='d'>today</span></li>
      <li class='x'><h2><a>Title 3</a></h2><span class='d'>today</span></li>
    </ul>
    """
    hits = extract_items_selectolax(
        html,
        ScraperSelectors(container="li.x", title="h2 > a", link="h2 > a", date=".d"),
    )
    assert [h.title for h in hits] == ["Title"]


def test_selectolax_tolerates_unclosed_tags_better_than_bs4_lxml() -> None:
    """Layer 2's whole point: recover items from pages that break lxml.

    This HTML has an unclosed <li> — lxml's recovery merges siblings into
    a single container in some cases. Selectolax's lexbor backend handles
    this differently and is the reason we keep Layer 2 as a distinct
    escalation. We don't assert a specific "more" number, only that
    selectolax produces at least as many hits as the BS4 path on this
    payload — otherwise Layer 2 has no fallback value at all.
    """
    html = """
    <ul>
      <li class='x'><h2><a href='/a'>A</a></h2><span class='d'>d1</span>
      <li class='x'><h2><a href='/b'>B</a></h2><span class='d'>d2</span>
      <li class='x'><h2><a href='/c'>C</a></h2><span class='d'>d3</span></li>
    </ul>
    """
    sel = ScraperSelectors(container="li.x", title="h2 > a", link="h2 > a", date=".d")
    bs4_hits = extract_items(html, sel)
    slx_hits = extract_items_selectolax(html, sel)
    assert len(slx_hits) >= len(bs4_hits)
    assert {h.link for h in slx_hits} >= {h.link for h in bs4_hits}


def test_parse_for_dispatches_to_selectolax(html: str) -> None:
    assert parse_for("selectolax", html, _SEL) == extract_items_selectolax(html, _SEL)


def test_parse_for_defaults_to_bs4_on_unknown_backend(html: str) -> None:
    """Unknown backend names must NOT crash — they fall back to BS4.

    This lets a layer forget to declare ``parser_name`` without taking
    down the whole run; the orchestrator still parses something sensible.
    """
    assert parse_for("", html, _SEL) == extract_items(html, _SEL)
    assert parse_for("nonsense", html, _SEL) == extract_items(html, _SEL)
