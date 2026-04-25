"""Tests for the block-detection escalate path in :class:`FetchOrchestrator`.

Kept separate from ``test_fetch_orchestrator.py`` (which pins the
ScrapeError-escalate semantics from Iter 8) so both paths stay regression-
proof. A breakage in the block-escalate integration should fail these
tests without touching the base suite.
"""

from __future__ import annotations

from scraper.block_detection import BlockVerdict, detect_block
from scraper.fetch_orchestrator import (
    FetchOrchestrator,
    OrchestratorResult,
    default_block_detector,
)
from scraper.layers.base import FetchResult, ScrapeError


class _StubLayer:
    """Minimal scripted layer — same shape as the one in test_fetch_orchestrator."""

    def __init__(self, layer_number: int, name: str, parser_name: str, script: list) -> None:
        self.layer_number = layer_number
        self.name = name
        self.parser_name = parser_name
        self._script = list(script)
        self.calls: list[str] = []

    def fetch(self, url: str, timeout: float = 20.0) -> FetchResult:
        self.calls.append(url)
        if not self._script:
            raise ScrapeError(f"{self.name}: script exhausted")
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def _ok(url: str, html: str = "<html><body>real content</body></html>") -> FetchResult:
    return FetchResult(url=url, html=html, status_code=200)


_CLOUDFLARE_HTML = (
    "<!DOCTYPE html><html><head><title>Just a moment...</title></head>"
    '<body><div class="cf-browser-verification"></div></body></html>'
)


def _noop_sleep(_: float) -> None:
    return None


# --------------------------------------------------------------------------- #


def test_orchestrator_treats_block_html_as_escalate_trigger() -> None:
    """Layer 1 returns 200 + Cloudflare HTML; Layer 2 returns real HTML.
    With the default block detector, Layer 2's result must win."""
    l1 = _StubLayer(1, "l1", "bs4", [_ok("u", _CLOUDFLARE_HTML)])
    l2 = _StubLayer(2, "l2", "selectolax", [_ok("u", "<html><body>ok</body></html>")])
    orch = FetchOrchestrator([l1, l2], block_detector=default_block_detector)

    result, errors = orch.fetch_with_fallback("u", max_retries=0, sleep=_noop_sleep)

    assert isinstance(result, OrchestratorResult)
    assert result.layer_number == 2
    assert "ok" in result.fetched.html
    assert l1.calls == ["u"]
    assert l2.calls == ["u"]
    # L1's error trail annotates that it was blocked, not that it raised.
    assert len(errors) == 1
    assert "layer 1" in errors[0]
    assert "blocked" in errors[0].lower()


def test_block_detection_retries_same_layer_within_budget() -> None:
    """If Layer 1 serves a block on attempt 1 but real content on attempt 2
    (within max_retries), L1 must still win — no escalation."""
    l1 = _StubLayer(
        1,
        "l1",
        "bs4",
        [_ok("u", _CLOUDFLARE_HTML), _ok("u", "<html><body>real</body></html>")],
    )
    l2 = _StubLayer(2, "l2", "selectolax", [_ok("u", "<other/>")])
    orch = FetchOrchestrator([l1, l2], block_detector=default_block_detector)

    result, errors = orch.fetch_with_fallback("u", max_retries=1, sleep=_noop_sleep)

    assert result is not None
    assert result.layer_number == 1
    assert "real" in result.fetched.html
    assert len(l1.calls) == 2
    assert l2.calls == []
    assert errors == []


def test_block_on_every_attempt_across_all_layers_fails_cascade() -> None:
    """All layers return blocker HTML → orchestrator reports full failure."""
    l1 = _StubLayer(1, "l1", "bs4", [_ok("u", _CLOUDFLARE_HTML)])
    l2 = _StubLayer(2, "l2", "selectolax", [_ok("u", _CLOUDFLARE_HTML)])
    orch = FetchOrchestrator([l1, l2], block_detector=default_block_detector)

    result, errors = orch.fetch_with_fallback("u", max_retries=0, sleep=_noop_sleep)

    assert result is None
    assert len(errors) == 2
    assert all("blocked" in e.lower() for e in errors)


def test_disabling_block_detector_restores_iter8_behaviour() -> None:
    """With ``block_detector=None``, Layer 1's 2xx Cloudflare response is
    accepted — the orchestrator must not inspect the HTML."""
    l1 = _StubLayer(1, "l1", "bs4", [_ok("u", _CLOUDFLARE_HTML)])
    l2 = _StubLayer(2, "l2", "selectolax", [_ok("u", "<html><body>ok</body></html>")])
    orch = FetchOrchestrator([l1, l2])  # no block_detector

    result, _ = orch.fetch_with_fallback("u", max_retries=0, sleep=_noop_sleep)

    assert result is not None
    assert result.layer_number == 1
    assert result.fetched.html == _CLOUDFLARE_HTML
    assert l2.calls == []


def test_default_block_detector_closes_over_fetch_result_html() -> None:
    """Sanity check — ``default_block_detector`` is just an adapter that
    forwards ``FetchResult.html`` to :func:`detect_block`."""
    fr = FetchResult(url="u", html=_CLOUDFLARE_HTML, status_code=200)
    assert default_block_detector(fr) == detect_block(_CLOUDFLARE_HTML)
    assert isinstance(default_block_detector(fr), BlockVerdict)
