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

Fallback triggers this iteration:

- Layer raises ``ScrapeError`` (network error, non-2xx status, or anything
  else the layer considers fatal).

Deliberately **not** fallback triggers this iteration:

- Layer returns 0 parsed hits. A truly-empty listing page would be
  indistinguishable from a soft-blocked one; the "zero hits → escalate"
  heuristic needs a block-detection signal (Iter 9).

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
from scraper.layers.base import FetchResult, ScrapeError
from scraper.layers.layer1_httpx import Layer1Httpx
from scraper.layers.layer2_selectolax import Layer2Selectolax

logger = logging.getLogger(__name__)

Sleeper = Callable[[float], None]


class _Fetcher(Protocol):
    """Structural type for the subset of :class:`Layer` the orchestrator uses."""

    name: str
    layer_number: int

    def fetch(self, url: str, timeout: float = 20.0) -> FetchResult: ...


@dataclass(frozen=True)
class OrchestratorResult:
    """Outcome of a successful fetch through the cascade."""

    fetched: FetchResult
    layer_number: int
    parser_name: str


class FetchOrchestrator:
    """Apply the layer cascade to a single URL."""

    def __init__(self, layers: list[_Fetcher]) -> None:
        if not layers:
            raise ValueError("FetchOrchestrator requires at least one layer")
        self._layers: list[_Fetcher] = list(layers)

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
    ) -> tuple[OrchestratorResult | None, list[str]]:
        """Attempt each layer in order; return the first success + per-layer errors.

        The second element of the tuple is a list of one error string per
        layer that failed — callers use it to annotate ``RunStats.errors``
        when the whole cascade gives up.
        """
        per_layer_errors: list[str] = []
        for layer in self._layers:
            attempts = max_retries + 1
            last_err: str | None = None
            for attempt in range(attempts):
                try:
                    fetched = layer.fetch(url)
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

    Layer 4 is not implemented yet; it is silently skipped so an over-eager
    user config does not crash the run.
    """
    # Deferred import — Layer 3 pulls Playwright at import time.
    from scraper.layers.layer3_playwright import Layer3Playwright

    layers: list[_Fetcher] = []
    for layer_num in source.enabled_layers:
        if layer_num == 1:
            layers.append(Layer1Httpx())
        elif layer_num == 2:
            layers.append(Layer2Selectolax())
        elif layer_num == 3:
            layers.append(Layer3Playwright())
        elif layer_num == 4:
            logger.info(
                "layer 4 requested for source %s but not implemented yet; skipping",
                source.name,
            )
        else:
            logger.warning("unknown layer %s for source %s; skipping", layer_num, source.name)
    if not layers:
        # Degrade gracefully — a source with only Layer 4 enabled still gets
        # *something*, rather than crashing the run.
        layers.append(Layer1Httpx())
    return layers


__all__ = [
    "FetchOrchestrator",
    "OrchestratorResult",
    "Sleeper",
    "build_layers_for_source",
]
