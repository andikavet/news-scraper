"""Tests for the Layer 2 fetcher (httpx-mobile + selectolax)."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from scraper.layers.base import ScrapeError
from scraper.layers.layer2_selectolax import Layer2Selectolax


def _patch_httpx_client(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    """Replace ``httpx.Client`` in Layer 2 with a MockTransport-backed one.

    Drops ``http2`` from kwargs because it requires the ``h2`` package
    which isn't a hard dependency of the test environment; the MockTransport
    doesn't care about HTTP version anyway.
    """

    real_client = httpx.Client  # capture before we patch the name

    def factory(**kw):  # type: ignore[no-untyped-def]
        kw.pop("http2", None)
        return real_client(transport=httpx.MockTransport(handler), **kw)

    monkeypatch.setattr("scraper.layers.layer2_selectolax.httpx.Client", factory)


def test_layer2_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Layer 2 returns HTML + status on 200."""
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(200, text="<html><body>ok</body></html>")

    _patch_httpx_client(monkeypatch, handler)
    result = Layer2Selectolax().fetch("https://example.test/news")
    assert result.status_code == 200
    assert "ok" in result.html
    # Mobile iOS Safari UA — distinguishes Layer 2 from Layer 1's desktop UA.
    assert "iPhone" in seen_headers["user-agent"]
    assert "Mobile" in seen_headers["user-agent"]
    # id-ID locale preference as the differentiator vs Layer 1's en-US-first.
    assert seen_headers["accept-language"].startswith("id-ID")


def test_layer2_declares_selectolax_as_its_parser() -> None:
    """The runner dispatches on ``parser_name``; Layer 2 must declare selectolax."""
    assert Layer2Selectolax.parser_name == "selectolax"
    assert Layer2Selectolax.layer_number == 2


def test_layer2_raises_scrapeerror_on_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="blocked")

    _patch_httpx_client(monkeypatch, handler)
    with pytest.raises(ScrapeError, match="HTTP 503"):
        Layer2Selectolax().fetch("https://example.test/news")


def test_layer2_raises_scrapeerror_on_network_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _patch_httpx_client(monkeypatch, handler)
    with pytest.raises(ScrapeError, match="network error"):
        Layer2Selectolax().fetch("https://example.test/news")
