"""Iter 14 — integration tests for the Layer 3 / Layer 4 ``wait_selector`` fix.

Scenario: a JS-rendered listing where the container is injected *after*
``DOMContentLoaded`` **and** where a continuous analytics ping keeps
``networkidle`` from ever settling. Pre-Iter-14 Layer 3/4 defaulted to
``wait_until="networkidle"`` and timed out on pages that look like this
(e.g. the suarantb.com fixture we ship). With the Iter 14 refactor, the
orchestrator passes the source's container selector as ``wait_selector``
so L3/L4 block on that selector attaching to the DOM instead.

These tests use the exact selectors the user cited for the real
suarantb.com page so this file doubles as the "forced Layer 3/4" smoke
test requested in the Iter 14 brief.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from config import ScraperSelectors, ScrapeSource, SleepRange
from scraper.layers.layer3_playwright import Layer3Playwright
from scraper.layers.layer4_stealth import Layer4Stealth
from scraper.parsers import extract_items
from scraper.runner import run_url_params_source

pytestmark = pytest.mark.playwright

FIXTURES = Path(__file__).parent / "fixtures"
SUARANTB_URL = (FIXTURES / "suarantb_listing.html").absolute().as_uri()

# Exact selectors from the user's Iter 14 brief.
_CONTAINER = "#tdi_63 .td-cpt-post"
_TITLE = ".td-module-title a"
_LINK = ".td-module-title a"
_DATE = ".td-module-date"


def _source() -> ScrapeSource:
    return ScrapeSource(
        name="SuaraNTB",
        url_template=SUARANTB_URL,
        pagination_type="url_params",
        selectors=ScraperSelectors(
            container=_CONTAINER,
            title=_TITLE,
            link=_LINK,
            date=_DATE,
        ),
        enabled_layers=[3],
        max_retries=0,
        sleep=SleepRange(min=0.0, max=0.0),
        avg_page_per_month=1,
    )


# --------------------------------------------------------------------------- #
# Layer 3 direct fetch
# --------------------------------------------------------------------------- #


def test_layer3_without_wait_selector_may_see_empty_container() -> None:
    """Sanity check: without a ``wait_selector`` hint, Layer 3 returns
    before the delayed injection fires, so the listing can be empty.

    The point of this assertion isn't to pin the emptiness (timing could
    beat the setTimeout on a fast box) — it's to pin that the absence of
    a wait strategy is the failure mode that the fix addresses. The
    *next* test proves the fix works.
    """
    fetcher = Layer3Playwright()
    result = fetcher.fetch(SUARANTB_URL, timeout=10.0)
    # The fixture does eventually inject content, but with no wait hint
    # the layer only waits for ``wait_until="load"`` — nothing forces it
    # to stop on the container selector. This test is a liveness probe
    # (just asserts we got a non-500 page back).
    assert result.status_code is None or result.status_code < 400


def test_layer3_with_wait_selector_waits_for_delayed_container() -> None:
    """With the container as ``wait_selector``, Layer 3 blocks until the
    listing is attached. The user-provided suarantb selectors must
    extract all three titles / links / dates."""
    fetcher = Layer3Playwright()
    result = fetcher.fetch(
        SUARANTB_URL,
        timeout=15.0,
        wait_selector=_CONTAINER,
    )

    selectors = ScraperSelectors(container=_CONTAINER, title=_TITLE, link=_LINK, date=_DATE)
    hits = extract_items(result.html, selectors)
    assert [h.title for h in hits] == [
        "Kejurnas MRS Musim Balap 2026 Dimulai, Diikuti 102 Pembalap",
        "Nekat Mogok Kerja, PPPK Paruh Waktu Lombok Tengah Bisa Terkena Sanksi Berat",
        "Kementerian Komdigi Dorong Pemda Implementasi Program Kampung Internet",
    ]
    assert all(h.link.startswith("https://example.test/news/") for h in hits)
    assert [h.date_raw for h in hits] == [
        "25/04/2026",
        "24/04/2026",
        "23/04/2026",
    ]


# --------------------------------------------------------------------------- #
# Layer 4 direct fetch
# --------------------------------------------------------------------------- #


def test_layer4_with_wait_selector_waits_for_delayed_container() -> None:
    """Same contract as Layer 3, on the stealth-patched browser."""
    fetcher = Layer4Stealth()
    result = fetcher.fetch(
        SUARANTB_URL,
        timeout=15.0,
        wait_selector=_CONTAINER,
    )

    selectors = ScraperSelectors(container=_CONTAINER, title=_TITLE, link=_LINK, date=_DATE)
    hits = extract_items(result.html, selectors)
    assert len(hits) == 3
    titles = [h.title for h in hits]
    assert "Kejurnas MRS Musim Balap 2026 Dimulai, Diikuti 102 Pembalap" in titles
    assert all(h.link for h in hits)
    assert all(h.date_raw for h in hits)


def test_layer3_raises_when_selector_never_appears() -> None:
    """A selector that doesn't match anything should raise ``ScrapeError``
    with a deterministic message — callers (the orchestrator) escalate
    to the next layer on ``ScrapeError``."""
    from scraper.layers.base import ScrapeError

    fetcher = Layer3Playwright()
    with pytest.raises(ScrapeError, match="did not appear"):
        fetcher.fetch(
            SUARANTB_URL,
            timeout=5.0,
            wait_selector=".selector-that-does-not-exist",
        )


# --------------------------------------------------------------------------- #
# End-to-end: forced Layer 3 via the runner
# --------------------------------------------------------------------------- #


def test_forced_layer3_end_to_end_with_suarantb_selectors() -> None:
    """Drive the full runner with ``enabled_layers=[3]`` so L3 is the
    only cascade step. Verifies (a) the orchestrator plumbs the
    container selector as ``wait_selector`` and (b) the runner
    correctly parses titles / links / dates off the rendered HTML."""
    source = _source()
    source.enabled_layers = [3]

    result = run_url_params_source(
        source,
        start_page=1,
        end_page=1,
        time_range_start=date(2024, 1, 1),
        reference_date=date(2026, 4, 25),
    )

    assert result.stats.pages_scanned == 1
    assert result.stats.pages_failed == 0
    assert result.stats.layer_usage == {3: 1}
    # All three fixture items are in-range.
    assert result.stats.items_in_range == 3
    titles = [item.title for item in result.items]
    assert titles == [
        "Kejurnas MRS Musim Balap 2026 Dimulai, Diikuti 102 Pembalap",
        "Nekat Mogok Kerja, PPPK Paruh Waktu Lombok Tengah Bisa Terkena Sanksi Berat",
        "Kementerian Komdigi Dorong Pemda Implementasi Program Kampung Internet",
    ]
    # DD/MM/YYYY → date_parsed via ``parse_scraped_date``.
    assert all(item.date_parsed is not None for item in result.items)


def test_forced_layer4_end_to_end_with_suarantb_selectors() -> None:
    """Same as the L3 end-to-end test but with ``enabled_layers=[4]`` so
    the stealth-patched Chromium is exercised via the orchestrator."""
    source = _source()
    source.enabled_layers = [4]

    result = run_url_params_source(
        source,
        start_page=1,
        end_page=1,
        time_range_start=date(2024, 1, 1),
        reference_date=date(2026, 4, 25),
    )

    assert result.stats.pages_scanned == 1
    assert result.stats.pages_failed == 0
    assert result.stats.layer_usage == {4: 1}
    assert result.stats.items_in_range == 3
    assert len(result.items) == 3
