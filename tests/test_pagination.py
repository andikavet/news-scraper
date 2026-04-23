"""Tests for the pagination strategy layer."""

from __future__ import annotations

import pytest

from config import ScraperSelectors, ScrapeSource
from scraper.pagination import (
    PaginationNotSupportedError,
    iter_page_requests,
    url_for_page,
)


def _make_source(
    pagination_type: str = "url_params",
    url_template: str = "https://portalx.test/news?page={page}",
) -> ScrapeSource:
    return ScrapeSource(
        name="PortalX",
        pagination_type=pagination_type,  # type: ignore[arg-type]
        url_template=url_template,
        selectors=ScraperSelectors(
            container="li.article-item",
            title="h2",
            link="h2 a",
            date="span.date-time",
        ),
    )


def test_url_for_page_substitutes_placeholder():
    src = _make_source()
    assert url_for_page(src, 1) == "https://portalx.test/news?page=1"
    assert url_for_page(src, 7) == "https://portalx.test/news?page=7"


def test_url_for_page_no_placeholder_returns_template_verbatim():
    src = _make_source(url_template="https://portalx.test/news")
    assert url_for_page(src, 3) == "https://portalx.test/news"


def test_iter_page_requests_yields_inclusive_range():
    src = _make_source()
    reqs = list(iter_page_requests(src, start_page=2, end_page=4))
    assert [r.page for r in reqs] == [2, 3, 4]
    assert reqs[0].url == "https://portalx.test/news?page=2"
    assert reqs[-1].url == "https://portalx.test/news?page=4"


def test_iter_page_requests_empty_when_start_gt_end():
    src = _make_source()
    assert list(iter_page_requests(src, start_page=5, end_page=3)) == []


def test_iter_page_requests_rejects_non_url_strategies():
    src_infinite = _make_source(pagination_type="infinite_scroll")
    src_click = _make_source(pagination_type="click_next")
    with pytest.raises(PaginationNotSupportedError):
        list(iter_page_requests(src_infinite, 1, 2))
    with pytest.raises(PaginationNotSupportedError):
        list(iter_page_requests(src_click, 1, 2))
