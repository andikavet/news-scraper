"""Tests for the 'Test Selector' tool (offline via monkeypatched Layer 1)."""

from __future__ import annotations

from pathlib import Path

from config import ScraperSelectors
from scraper.layers.base import FetchResult, ScrapeError
from scraper.selector_tester import run_selector_test


def _fixture() -> str:
    return (Path(__file__).parent / "fixtures" / "portalx_listing.html").read_text(encoding="utf-8")


def test_test_selector_happy_path(monkeypatch):
    from scraper.layers import layer1_httpx

    def fake_fetch(self, url: str, timeout: float = 20.0):  # noqa: ARG001
        return FetchResult(url=url, html=_fixture(), status_code=200)

    monkeypatch.setattr(layer1_httpx.Layer1Httpx, "fetch", fake_fetch)

    result = run_selector_test(
        "https://example.com/",
        ScraperSelectors(
            container="li.article-item",
            title="h2 > a",
            link="h2 > a",
            date=".date-time",
        ),
    )
    assert result.ok is True
    assert result.status_code == 200
    assert len(result.items) == 3
    assert result.items[0].title.startswith("Inflasi")


def test_test_selector_propagates_fetch_error(monkeypatch):
    from scraper.layers import layer1_httpx

    def fake_fetch(self, url: str, timeout: float = 20.0):  # noqa: ARG001
        raise ScrapeError("connection refused")

    monkeypatch.setattr(layer1_httpx.Layer1Httpx, "fetch", fake_fetch)

    result = run_selector_test(
        "https://example.com/",
        ScraperSelectors(
            container="li.article-item",
            title="h2 > a",
            link="h2 > a",
            date=".date-time",
        ),
    )
    assert result.ok is False
    assert result.error == "connection refused"
    assert result.items == []


def test_test_selector_zero_hits_still_ok(monkeypatch):
    from scraper.layers import layer1_httpx

    def fake_fetch(self, url: str, timeout: float = 20.0):  # noqa: ARG001
        return FetchResult(url=url, html="<html></html>", status_code=200)

    monkeypatch.setattr(layer1_httpx.Layer1Httpx, "fetch", fake_fetch)

    result = run_selector_test(
        "https://example.com/",
        ScraperSelectors(container=".none", title="a", link="a", date="a"),
    )
    assert result.ok is True
    assert result.items == []
