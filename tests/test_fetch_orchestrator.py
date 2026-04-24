"""Tests for :class:`scraper.fetch_orchestrator.FetchOrchestrator`.

The orchestrator is the pivot of the Iter 8 cascade: it tries each enabled
layer in order and stops on the first success. These tests drive it with
stub layers that are trivially controllable so the fallback semantics are
pinned down independently of the runner and of any HTTP client.
"""

from __future__ import annotations

import pytest

from config import ScraperSelectors, ScrapeSource
from scraper.fetch_orchestrator import (
    FetchOrchestrator,
    OrchestratorResult,
    build_layers_for_source,
)
from scraper.layers.base import FetchResult, ScrapeError


class _StubLayer:
    """Deterministic stand-in for a real Layer.

    ``script`` is consumed one entry per attempt — each entry is either a
    ``FetchResult`` (return) or an ``Exception`` (raise). Lets us model
    "layer 1 fails 3 times" vs "layer 2 succeeds on the 2nd try" etc.
    """

    def __init__(
        self,
        layer_number: int,
        name: str,
        parser_name: str,
        script: list,
    ) -> None:
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


def _ok(url: str, html: str = "<html/>") -> FetchResult:
    return FetchResult(url=url, html=html, status_code=200)


def _noop_sleep(_: float) -> None:  # pragma: no cover - trivial
    return None


# --------------------------------------------------------------------------- #


def test_stops_on_first_success_and_does_not_touch_later_layers() -> None:
    l1 = _StubLayer(1, "l1", "bs4", [_ok("u", "<l1/>")])
    l2 = _StubLayer(2, "l2", "selectolax", [_ok("u", "<l2/>")])
    orch = FetchOrchestrator([l1, l2])

    result, errors = orch.fetch_with_fallback("u", max_retries=0, sleep=_noop_sleep)

    assert isinstance(result, OrchestratorResult)
    assert result.layer_number == 1
    assert result.parser_name == "bs4"
    assert result.fetched.html == "<l1/>"
    assert errors == []
    # Layer 2 must not have been called.
    assert l1.calls == ["u"]
    assert l2.calls == []


def test_escalates_to_next_layer_when_prior_exhausts_retries() -> None:
    """Layer 1 fails every retry; Layer 2 succeeds first try → Layer 2 wins."""
    l1 = _StubLayer(
        1,
        "l1",
        "bs4",
        [ScrapeError("l1 blocked"), ScrapeError("l1 blocked"), ScrapeError("l1 blocked")],
    )
    l2 = _StubLayer(2, "l2", "selectolax", [_ok("u", "<l2/>")])
    orch = FetchOrchestrator([l1, l2])

    result, errors = orch.fetch_with_fallback("u", max_retries=2, sleep=_noop_sleep)

    assert result is not None
    assert result.layer_number == 2
    assert result.parser_name == "selectolax"
    assert result.fetched.html == "<l2/>"
    # L1 tried max_retries+1 == 3 times before escalation.
    assert len(l1.calls) == 3
    assert len(l2.calls) == 1
    # Per-layer error list captures the L1 failure.
    assert len(errors) == 1
    assert "layer 1" in errors[0]
    assert "l1 blocked" in errors[0]


def test_returns_none_when_every_layer_fails() -> None:
    l1 = _StubLayer(1, "l1", "bs4", [ScrapeError("l1 blocked")])
    l2 = _StubLayer(2, "l2", "selectolax", [ScrapeError("l2 blocked")])
    l3 = _StubLayer(3, "l3", "bs4", [ScrapeError("l3 blocked")])
    orch = FetchOrchestrator([l1, l2, l3])

    result, errors = orch.fetch_with_fallback("u", max_retries=0, sleep=_noop_sleep)

    assert result is None
    # One error per layer, in layer order.
    assert len(errors) == 3
    assert "layer 1" in errors[0]
    assert "layer 2" in errors[1]
    assert "layer 3" in errors[2]


def test_retries_within_a_layer_before_escalating() -> None:
    """Transient failure → retry same layer, succeed without escalating."""
    l1 = _StubLayer(1, "l1", "bs4", [ScrapeError("flaky"), _ok("u", "<l1/>")])
    l2 = _StubLayer(2, "l2", "selectolax", [_ok("u", "<l2/>")])
    orch = FetchOrchestrator([l1, l2])

    result, errors = orch.fetch_with_fallback("u", max_retries=1, sleep=_noop_sleep)

    assert result is not None
    assert result.layer_number == 1  # L1 succeeded on retry — no escalation.
    assert result.fetched.html == "<l1/>"
    assert len(l1.calls) == 2
    assert l2.calls == []
    assert errors == []


def test_retry_backoff_sleeps_between_attempts() -> None:
    """Retry backoff must call ``sleep`` before each non-first attempt."""
    slept: list[float] = []

    l1 = _StubLayer(
        1,
        "l1",
        "bs4",
        [ScrapeError("a"), ScrapeError("b"), ScrapeError("c")],
    )
    l2 = _StubLayer(2, "l2", "selectolax", [_ok("u")])
    orch = FetchOrchestrator([l1, l2])
    orch.fetch_with_fallback(
        "u", max_retries=2, sleep=lambda s: slept.append(s), retry_backoff=0.25
    )
    # 3 attempts on L1 → 2 inter-attempt sleeps (0.25, 0.5). None between
    # L1's last attempt and L2's first — escalation is instant.
    # L2 succeeds on first try → no additional sleep.
    assert slept == [0.25, 0.5]


def test_orchestrator_requires_at_least_one_layer() -> None:
    with pytest.raises(ValueError, match="at least one layer"):
        FetchOrchestrator([])


def test_layer_numbers_reflects_input_order() -> None:
    l2 = _StubLayer(2, "l2", "selectolax", [])
    l1 = _StubLayer(1, "l1", "bs4", [])
    orch = FetchOrchestrator([l2, l1])
    assert orch.layer_numbers == [2, 1]


# --------------------------------------------------------------------------- #
# build_layers_for_source
# --------------------------------------------------------------------------- #


def _source(enabled: list[int]) -> ScrapeSource:
    return ScrapeSource(
        name="s",
        pagination_type="url_params",
        url_template="https://s.test/?p={page}",
        selectors=ScraperSelectors(container="li", title="a", link="a", date=".d"),
        enabled_layers=enabled,  # type: ignore[arg-type]
    )


def test_build_layers_for_source_respects_config_order_with_layers_1_and_2() -> None:
    layers = build_layers_for_source(_source([1, 2]))
    assert [layer.layer_number for layer in layers] == [1, 2]
    # Parser names propagate so the runner knows which backend to use.
    assert [getattr(layer, "parser_name", "bs4") for layer in layers] == ["bs4", "selectolax"]


def test_build_layers_for_source_resolves_layer_4_stealth() -> None:
    """Iter 9: Layer 4 is now a first-class layer and must be wired in."""
    # enabled_layers validator sorts + dedupes.
    layers = build_layers_for_source(_source([1, 4]))
    assert [layer.layer_number for layer in layers] == [1, 4]


def test_build_layers_for_source_degrades_gracefully_when_all_unknown() -> None:
    """If every configured layer is unknown, fall back to L1.

    A run is more useful than a crash — the user still gets SOMETHING to
    look at and can fix their config. ``ScrapeSource.enabled_layers`` is
    typed ``Literal[1, 2, 3, 4]`` so unknown layer numbers can only appear
    if the config model is bypassed; we construct such a source directly
    to exercise the safety net.
    """
    src = _source([1])
    src = src.model_copy(update={"enabled_layers": [99]})  # type: ignore[arg-type]
    layers = build_layers_for_source(src)
    assert [layer.layer_number for layer in layers] == [1]
