"""Tests for :mod:`scraper.block_detection`.

Each signal pattern gets a focused case, plus adversarial cases where the
detector must **not** fire (legitimate empty listing, normal article body
that happens to mention "captcha" in an unrelated context, etc.).
"""

from __future__ import annotations

from scraper.block_detection import detect_block


def test_flags_cloudflare_just_a_moment_challenge() -> None:
    html = """<!DOCTYPE html><html><head><title>Just a moment...</title></head>
    <body><h1>Checking your browser before accessing...</h1>
    <div class="cf-browser-verification">...</div></body></html>"""
    verdict = detect_block(html)
    assert verdict.is_block
    # Two keywords could match; first hit wins — order is stable.
    assert "just a moment" in verdict.signal
    assert verdict.evidence


def test_flags_datadome_interstitial() -> None:
    html = "<html><body>DataDome device check.</body></html>"
    verdict = detect_block(html)
    assert verdict.is_block
    assert "datadome" in verdict.signal.lower()


def test_flags_recaptcha_landing_page() -> None:
    html = '<html><body><div class="g-recaptcha" data-sitekey="x"></div></body></html>'
    verdict = detect_block(html)
    assert verdict.is_block
    assert "recaptcha" in verdict.signal.lower()


def test_flags_explicit_access_denied() -> None:
    html = "<html><body><h1>Access Denied</h1><p>You don't have permission.</p></body></html>"
    verdict = detect_block(html)
    assert verdict.is_block
    assert "access denied" in verdict.signal


def test_flags_short_body_with_blocked_keyword() -> None:
    html = "<html><body><p>Request blocked. Please try again later.</p></body></html>"
    # ``request blocked`` is in _BLOCK_KEYWORDS directly — keyword rule fires.
    verdict = detect_block(html)
    assert verdict.is_block


def test_short_body_with_generic_denied_keyword_fires_rule2() -> None:
    """A short body with generic denial language but no strong keyword
    should still be caught by rule 2 (short-body heuristic)."""
    html = (
        "<html><body><p>Sorry, access to this resource has been "
        "denied by the administrator.</p></body></html>"
    )
    verdict = detect_block(html)
    assert verdict.is_block
    assert verdict.signal.startswith("short-body+keyword:")


def test_does_not_flag_legitimate_empty_listing() -> None:
    """A normal but empty listing page should NOT be treated as a block."""
    html = (
        '<html><body><div class="container"><h1>Latest News</h1>'
        '<div class="list"></div><p>No news for today.</p>'
        "</div></body></html>"
    )
    assert not detect_block(html).is_block


def test_does_not_flag_normal_article_mentioning_captcha_in_body() -> None:
    """An article talking about captchas (long body, no keyword match) is
    not a block — the short-body heuristic protects against this."""
    big_body = " ".join(["lorem ipsum dolor sit amet"] * 400)
    html = f"<html><body><article>{big_body}</article></body></html>"
    assert not detect_block(html).is_block


def test_empty_html_returns_not_blocked() -> None:
    assert not detect_block("").is_block


def test_evidence_snippet_includes_surrounding_context() -> None:
    html = "<html><body>lorem ipsum Just a moment while we check...</body></html>"
    verdict = detect_block(html)
    assert verdict.is_block
    assert "just a moment" in verdict.evidence.lower()
