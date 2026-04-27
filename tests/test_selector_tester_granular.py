"""Tests for the Iter 12 granular Test Selector output.

Exercises the per-selector check structure (container / title / link /
date) that the Settings-page UI uses to differentiate which selector
worked vs which one failed.
"""

from __future__ import annotations

from config import ScraperSelectors
from scraper.layers.base import FetchResult
from scraper.selector_tester import run_selector_test

_HTML_GOOD = """
<html><body>
  <ul>
    <li class='card'>
      <h2><a href='/a'>Title A</a></h2>
      <span class='date'>01 Apr 2026</span>
    </li>
    <li class='card'>
      <h2><a href='/b'>Title B</a></h2>
      <span class='date'>02 Apr 2026</span>
    </li>
  </ul>
</body></html>
"""

_HTML_NO_DATE = """
<html><body>
  <ul>
    <li class='card'>
      <h2><a href='/a'>Title A</a></h2>
    </li>
  </ul>
</body></html>
"""

_HTML_NO_CONTAINER = "<html><body><p>nothing here</p></body></html>"


def _patch_layer(monkeypatch, html: str) -> None:
    from scraper.layers import layer1_httpx

    def fake_fetch(self, url: str, timeout: float = 20.0):  # noqa: ARG001
        return FetchResult(url=url, html=html, status_code=200)

    monkeypatch.setattr(layer1_httpx.Layer1Httpx, "fetch", fake_fetch)


def test_all_selectors_match_produces_four_passing_checks(monkeypatch):
    _patch_layer(monkeypatch, _HTML_GOOD)
    result = run_selector_test(
        "https://example.com/",
        ScraperSelectors(container="li.card", title="h2 a", link="h2 a", date=".date"),
    )
    assert result.ok
    assert len(result.checks) == 4
    by_name = {c.name: c for c in result.checks}
    assert {"container", "title", "link", "date"} == set(by_name)
    assert by_name["container"].matched
    assert by_name["title"].matched
    assert by_name["link"].matched
    assert by_name["date"].matched
    # Container's samples should reflect the count, not the text.
    assert "2 container" in by_name["container"].samples[0]
    # Title samples should be the actual extracted strings.
    assert "Title A" in by_name["title"].samples
    assert "Title B" in by_name["title"].samples


def test_missing_date_marked_as_failed_with_explicit_message(monkeypatch):
    _patch_layer(monkeypatch, _HTML_NO_DATE)
    result = run_selector_test(
        "https://example.com/",
        ScraperSelectors(container="li.card", title="h2 a", link="h2 a", date=".date"),
    )
    assert result.ok
    by_name = {c.name: c for c in result.checks}
    assert by_name["container"].matched
    assert by_name["title"].matched
    assert by_name["link"].matched
    assert not by_name["date"].matched
    assert by_name["date"].error is not None
    assert ".date" in by_name["date"].error
    assert "container" in by_name["date"].error.lower()


def test_no_containers_marks_subselectors_as_skipped_not_failed(monkeypatch):
    """If container fails, sub-selectors should report 'skipped' explicitly.

    Otherwise the user sees 4 generic 'not found' messages and can't tell
    whether to fix the container or the sub-selectors.
    """
    _patch_layer(monkeypatch, _HTML_NO_CONTAINER)
    result = run_selector_test(
        "https://example.com/",
        ScraperSelectors(container="li.card", title="h2 a", link="h2 a", date=".date"),
    )
    assert result.ok
    by_name = {c.name: c for c in result.checks}
    assert not by_name["container"].matched
    for name in ("title", "link", "date"):
        assert not by_name[name].matched
        assert "skipped" in by_name[name].error.lower()


def test_partial_misses_surface_warning_in_check_error(monkeypatch):
    """Selector matched on some containers but missed on others — warn, don't fail.

    A passing check with a non-None ``error`` is the structured form of
    that mixed signal.
    """
    html = """
    <ul>
      <li class='card'><h2><a href='/a'>A</a></h2><span class='date'>1</span></li>
      <li class='card'><h2><a href='/b'>B</a></h2></li>
    </ul>
    """
    _patch_layer(monkeypatch, html)
    result = run_selector_test(
        "https://example.com/",
        ScraperSelectors(container="li.card", title="h2 a", link="h2 a", date=".date"),
    )
    assert result.ok
    by_name = {c.name: c for c in result.checks}
    assert by_name["date"].matched is True
    assert by_name["date"].error is not None
    assert "1 of 2" in by_name["date"].error
