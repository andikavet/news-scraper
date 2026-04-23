"""Tests for ``scraper.parsers.extract_items``."""

from __future__ import annotations

from pathlib import Path

import pytest

from config import ScraperSelectors
from scraper.parsers import extract_items

_FIXTURE = Path(__file__).parent / "fixtures" / "portalx_listing.html"


@pytest.fixture
def html() -> str:
    return _FIXTURE.read_text(encoding="utf-8")


def test_extract_items_happy_path(html: str) -> None:
    hits = extract_items(
        html,
        ScraperSelectors(
            container="li.article-item",
            title="h2 > a",
            link="h2 > a",
            date=".date-time",
        ),
    )
    # The sponsor slot has neither title nor href -> skipped.
    assert len(hits) == 3
    titles = [h.title for h in hits]
    assert titles == [
        "Inflasi turun ke 2,3% bulan ini",
        "Ekspor non-migas naik 8%",
        "APBN 2026 disahkan DPR",
    ]
    assert hits[1].link == "https://portalx.test/berita/ekspor-naik"
    assert hits[0].link == "/berita/inflasi-turun"
    assert hits[0].date_raw == "5 menit lalu"


def test_extract_items_missing_container_returns_empty(html: str) -> None:
    hits = extract_items(
        html,
        ScraperSelectors(
            container=".does-not-exist",
            title="h2",
            link="a",
            date=".date-time",
        ),
    )
    assert hits == []


def test_extract_items_skips_partial_rows() -> None:
    html = """
    <ul>
      <li class='x'><h2><a href='/a'>Title</a></h2><span class='d'>today</span></li>
      <li class='x'><h2></h2><span class='d'>today</span></li>
      <li class='x'><h2><a>Title 3</a></h2><span class='d'>today</span></li>
    </ul>
    """
    hits = extract_items(
        html,
        ScraperSelectors(container="li.x", title="h2 > a", link="h2 > a", date=".d"),
    )
    # Row 2 has no title; row 3 has title but no href.
    assert [h.title for h in hits] == ["Title"]
