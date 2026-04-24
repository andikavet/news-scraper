"""Smoke tests for :class:`scraper.layers.layer4_stealth.Layer4Stealth`.

Two flavours:

1. **Unit-level** (always runs) — verifies the UA pool rotation logic and
   constructor invariants without booting Chromium.
2. **Integration** (marked ``playwright``, skipped if chromium is missing
   \u2014 see ``conftest.py``) — launches a real stealth context and asserts
   the patched fingerprint values survive into the page scope.
"""

from __future__ import annotations

import random

import pytest

from scraper.layers.layer4_stealth import Layer4Stealth


def test_layer_metadata_is_correct() -> None:
    l4 = Layer4Stealth()
    assert l4.layer_number == 4
    assert l4.name == "playwright-stealth"
    assert l4.parser_name == "bs4"


def test_empty_ua_pool_rejected() -> None:
    with pytest.raises(ValueError):
        Layer4Stealth(ua_pool=())


def test_ua_pool_rotation_uses_injected_rng() -> None:
    """Picks are deterministic when a seeded ``rng`` is provided \u2014
    this is what test doubles rely on."""
    pool = ("UA-A", "UA-B", "UA-C")
    l4 = Layer4Stealth(ua_pool=pool, rng=random.Random(42))
    picks = [l4._pick_user_agent() for _ in range(10)]
    # All picks come from the pool.
    assert all(p in pool for p in picks)
    # The sequence is deterministic given the seed.
    expected = [random.Random(42).choice(pool) for _ in range(1)][0]
    assert picks[0] == expected


def test_default_ua_pool_contains_chrome_user_agents() -> None:
    """Sanity check — every UA in the default pool identifies as Chrome/Edge.
    A regression where a Googlebot UA slipped in would be an obvious tell."""
    l4 = Layer4Stealth(rng=random.Random(0))
    picks = {l4._pick_user_agent() for _ in range(40)}
    assert picks, "should have seen at least one pick"
    assert all("Chrome/" in ua for ua in picks)


# --------------------------------------------------------------------------- #
# Real-browser integration check
# --------------------------------------------------------------------------- #


@pytest.mark.playwright
def test_navigator_webdriver_is_undefined_inside_stealth_context(tmp_path) -> None:
    """Load an in-memory HTML page that reads navigator.webdriver into the
    document body \u2014 assert it comes back as 'undefined'.

    Default Playwright contexts leak ``navigator.webdriver === true``; the
    init script should rewrite it. A regression here means the stealth
    patches are not being applied."""
    html = """<!DOCTYPE html><html><body><pre id="out"></pre>
    <script>
    document.getElementById('out').textContent =
        'webdriver=' + String(navigator.webdriver) +
        ' plugins=' + navigator.plugins.length +
        ' langs=' + navigator.languages.join(',');
    </script></body></html>"""

    fixture = tmp_path / "probe.html"
    fixture.write_text(html, encoding="utf-8")
    url = fixture.as_uri()

    l4 = Layer4Stealth(block_resources=False, wait_until="load")
    result = l4.fetch(url, timeout=15.0)

    assert "webdriver=undefined" in result.html
    # Plugin-count shim should produce a non-zero count.
    assert "plugins=3" in result.html
    assert "id-ID" in result.html
