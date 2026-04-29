"""Fetch orchestrator — the Layer 1 → Layer 2 → Layer 3 fallback cascade.

Given an ordered list of :class:`~scraper.layers.base.Layer` instances, the
orchestrator tries each one in sequence for a given URL. If a layer raises
:class:`~scraper.layers.base.ScrapeError` after exhausting its retries, the
orchestrator escalates to the next layer. The first layer that returns a
:class:`~scraper.layers.base.FetchResult` wins — its fetched HTML *and*
declared ``parser_name`` are returned so downstream code parses with the
same backend the succeeding layer was designed for.

The orchestrator is completely decoupled from per-source config — the
caller is responsible for translating ``source.enabled_layers`` into a
concrete list of :class:`Layer` instances via :func:`build_layers_for_source`.

Fallback triggers:

- Layer raises ``ScrapeError`` (network error, non-2xx status, or anything
  else the layer considers fatal).
- **Iter 9:** Layer returns a 2xx ``FetchResult`` whose HTML is a soft-block
  (Cloudflare / captcha / access-denied interstitial). The orchestrator
  consults an optional ``block_detector`` after every successful fetch;
  if the detector says the page is a block, the attempt is treated
  identically to a ``ScrapeError`` (retry same layer, then escalate).

Deliberately **not** a fallback trigger:

- Layer returns 0 parsed hits without any block signal. A truly-empty
  listing page is indistinguishable from a healthy "no news today" page,
  so 0-hits-alone is never enough to escalate. Callers that *do* want
  0-hits to escalate should combine selectors + block keywords into
  their own ``block_detector`` closure (see :mod:`scraper.block_detection`).

Per-layer retries still apply *within* each step of the cascade — if the
user configures ``max_retries=2`` and there are 3 enabled layers, the
worst case is 3 attempts × 3 layers = 9 fetches before the page is
declared failed. Sleeps between retries use the same ``retry_backoff``
schedule as the Iter 3 runner.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from config import ScrapeSource
from scraper.block_detection import BlockVerdict, detect_block
from scraper.layers.base import FetchResult, ScrapeError
from scraper.layers.layer1_httpx import Layer1Httpx
from scraper.layers.layer2_selectolax import Layer2Selectolax

logger = logging.getLogger(__name__)

Sleeper = Callable[[float], None]
BlockDetector = Callable[[FetchResult], BlockVerdict]


class _Fetcher(Protocol):
    """Structural type for the subset of :class:`Layer` the orchestrator uses."""

    name: str
    layer_number: int

    def fetch(
        self,
        url: str,
        timeout: float = 20.0,
        *,
        wait_selector: str | None = None,
    ) -> FetchResult: ...


@dataclass(frozen=True)
class OrchestratorResult:
    """Outcome of a successful fetch through the cascade."""

    fetched: FetchResult
    layer_number: int
    parser_name: str


class FetchOrchestrator:
    """Apply the layer cascade to a single URL.

    If ``block_detector`` is provided, each successful fetch is run through
    it before the orchestrator commits to it. A positive verdict is
    treated as a synthetic ``ScrapeError`` — the attempt counts against
    the layer's retry budget, and the cascade escalates normally once the
    budget is exhausted.
    """

    def __init__(
        self,
        layers: list[_Fetcher],
        *,
        block_detector: BlockDetector | None = None,
    ) -> None:
        if not layers:
            raise ValueError("FetchOrchestrator requires at least one layer")
        self._layers: list[_Fetcher] = list(layers)
        self._block_detector: BlockDetector | None = block_detector

    @property
    def layer_numbers(self) -> list[int]:
        return [layer.layer_number for layer in self._layers]

    def fetch_with_fallback(
        self,
        url: str,
        max_retries: int,
        sleep: Sleeper,
        *,
        retry_backoff: float = 2.0,
        wait_selector: str | None = None,
    ) -> tuple[OrchestratorResult | None, list[str]]:
        """Attempt each layer in order; return the first success + per-layer errors.

        The second element of the tuple is a list of one error string per
        layer that failed — callers use it to annotate ``RunStats.errors``
        when the whole cascade gives up.

        ``wait_selector`` (Iter 14) is forwarded to each layer's
        :meth:`fetch`. JS-rendered layers (3 & 4) use it to block on the
        container attaching to the DOM before returning; HTTP-only
        layers (1 & 2) ignore it.
        """
        per_layer_errors: list[str] = []
        for layer in self._layers:
            attempts = max_retries + 1
            last_err: str | None = None
            for attempt in range(attempts):
                try:
                    fetched = _call_layer_fetch(layer, url, wait_selector)
                except ScrapeError as e:
                    last_err = str(e)
                    logger.warning(
                        "layer %s fetch failed (attempt %d/%d): %s",
                        layer.name,
                        attempt + 1,
                        attempts,
                        e,
                    )
                    if attempt + 1 < attempts:
                        sleep(retry_backoff * (attempt + 1))
                    continue
                # Iter 9 — soft-block check. A 2xx response whose body is a
                # challenge/captcha page counts as a failed attempt so the
                # orchestrator escalates to a stealthier layer.
                if self._block_detector is not None:
                    verdict = self._block_detector(fetched)
                    if verdict.is_block:
                        last_err = f"blocked: {verdict.signal} ({verdict.evidence!r})"
                        logger.warning(
                            "layer %s soft-blocked (attempt %d/%d): %s",
                            layer.name,
                            attempt + 1,
                            attempts,
                            verdict.signal,
                        )
                        if attempt + 1 < attempts:
                            sleep(retry_backoff * (attempt + 1))
                        continue
                parser_name = getattr(layer, "parser_name", "bs4")
                return (
                    OrchestratorResult(
                        fetched=fetched,
                        layer_number=layer.layer_number,
                        parser_name=parser_name,
                    ),
                    per_layer_errors,
                )
            # This layer exhausted all its retries — record and escalate.
            per_layer_errors.append(f"layer {layer.layer_number} ({layer.name}): {last_err}")
            logger.info(
                "layer %s exhausted after %d attempts for %s; escalating",
                layer.name,
                attempts,
                url,
            )
        return None, per_layer_errors


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #


def build_layers_for_source(source: ScrapeSource) -> list[_Fetcher]:
    """Translate ``source.enabled_layers`` into concrete layer instances.

    Only layers compatible with the single-shot ``fetch(url) -> FetchResult``
    contract are returned — for ``url_params`` sources that's Layer 1, 2, and
    (at a pinch) Layer 3 used as a single-shot fallback. Layer 3 used as a
    *persistent browser session* for infinite_scroll/click_next is handled
    separately by :mod:`scraper.playwright_session` and is not part of the
    fallback cascade.

    Iter 9: Layer 4 (stealth Playwright) is now implemented. Unknown layer
    numbers are still silently skipped so a forward-compatible config does
    not crash the run.
    """
    # Deferred imports — Layer 3/4 pull Playwright at import time.
    from scraper.layers.layer3_playwright import Layer3Playwright
    from scraper.layers.layer4_stealth import Layer4Stealth

    layers: list[_Fetcher] = []
    for layer_num in source.enabled_layers:
        if layer_num == 1:
            layers.append(Layer1Httpx())
        elif layer_num == 2:
            layers.append(Layer2Selectolax())
        elif layer_num == 3:
            layers.append(Layer3Playwright())
        elif layer_num == 4:
            layers.append(Layer4Stealth())
        else:
            logger.warning("unknown layer %s for source %s; skipping", layer_num, source.name)
    if not layers:
        # Degrade gracefully — a source with only Layer 4 enabled still gets
        # *something*, rather than crashing the run.
        layers.append(Layer1Httpx())
    return layers


def _call_layer_fetch(layer: _Fetcher, url: str, wait_selector: str | None) -> FetchResult:
    """Invoke ``layer.fetch`` with ``wait_selector`` when the layer accepts it.

    Older layers (and test doubles) don't declare the ``wait_selector``
    keyword. We catch ``TypeError`` on the first call and retry without
    the kwarg so the protocol extension is backward-compatible.
    """
    if wait_selector is None:
        return layer.fetch(url)
    try:
        return layer.fetch(url, wait_selector=wait_selector)
    except TypeError as e:
        # Only swallow the specific "unexpected keyword argument" flavour.
        # Any other TypeError (real bug in the layer) still propagates.
        if "wait_selector" in str(e):
            return layer.fetch(url)
        raise


def default_block_detector(fetched: FetchResult) -> BlockVerdict:
    """Convenience adapter so callers can pass a bare function to the
    orchestrator without having to thread selectors through."""
    return detect_block(fetched.html)


__all__ = [
    "BlockDetector",
    "FetchOrchestrator",
    "OrchestratorResult",
    "Sleeper",
    "build_layers_for_source",
    "default_block_detector",
]
