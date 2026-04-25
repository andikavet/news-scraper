"""Deterministic soft-block detection for fetched HTML.

A "soft block" is a 2xx HTTP response whose body is NOT the content the
scraper asked for — typically a Cloudflare challenge page, a captcha
interstitial, or a "we've detected unusual activity" notice. The response
itself looks healthy to httpx, but the page content is useless to the
parser.

This module is the single source of truth for what counts as a block.
:class:`scraper.fetch_orchestrator.FetchOrchestrator` consults it between
a layer's successful fetch and declaring that fetch "delivered" — if the
detector says the page is a block, the orchestrator treats the attempt as
failed and escalates just like it would for a ``ScrapeError``.

Design goals:

- **Deterministic.** No ML, no heuristic tuning knobs. Every signal is a
  keyword match or a structural check that a reviewer can reason about.
- **No false positives on legitimate empty pages.** A category listing
  with zero articles yesterday still returns ``is_block=False`` — the
  "zero hits" signal must be paired with a short body AND a blocker
  keyword before we escalate.
- **No HTML parsing dependency.** Uses plain substring search on the
  lowercased HTML so it's cheap to call on every fetched page.

If this returns ``is_block=True``, the calling layer is, from the
orchestrator's perspective, indistinguishable from one that raised
``ScrapeError`` — same retry, same escalation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Tokens that strongly indicate a bot-challenge / access-denied page.
# Matched case-insensitively against the full HTML.
_BLOCK_KEYWORDS: tuple[str, ...] = (
    # Cloudflare / Akamai / general bot challenges
    "just a moment",
    "checking your browser",
    "cf-browser-verification",
    "cf-chl-bypass",
    "challenge-platform",
    "attention required",
    "please enable cookies",
    # DataDome / PerimeterX / generic blockers
    "datadome",
    "perimeterx",
    "distil",
    "px-captcha",
    "request blocked",
    # Explicit access-denied phrasing
    "access denied",
    "access is denied",
    "you have been blocked",
    "blocked by",
    "suspicious activity",
    # Captcha flows (hcaptcha / reCAPTCHA landing pages)
    "hcaptcha",
    "recaptcha",
    "g-recaptcha",
)

# Short body threshold — pages under this many characters of visible text
# combined with a blocker keyword are high-confidence blocks even if the
# selectors happened to match something spurious.
_SHORT_BODY_CHARS = 1500


@dataclass(frozen=True)
class BlockVerdict:
    """Structured decision from :func:`detect_block`.

    ``is_block`` is the actionable bit. ``signal`` names the rule that
    fired (for logs + error messages), and ``evidence`` is a short snippet
    of the matched text so a human debugging a run can see exactly why.
    """

    is_block: bool
    signal: str = ""
    evidence: str = ""


def _strip_tags(html: str) -> str:
    """Rough visible-text estimate. Not HTML-correct, but good enough to
    distinguish a 50-byte challenge page from a full listing page."""
    # Drop <script> and <style> blocks entirely so their body doesn't count.
    no_scripts = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    # Strip all remaining tags.
    text = re.sub(r"<[^>]+>", " ", no_scripts)
    return re.sub(r"\s+", " ", text).strip()


def detect_block(html: str) -> BlockVerdict:
    """Return a :class:`BlockVerdict` for ``html``.

    The decision is a layered OR:

    1. If any of :data:`_BLOCK_KEYWORDS` appears in the HTML → **block**.
       These keywords are specific enough that a legitimate article body
       would not contain them casually.
    2. Else if the visible text body is very short (< ``_SHORT_BODY_CHARS``
       chars) AND contains a generic block-indicator word (``blocked``,
       ``captcha``, ``forbidden``, ``denied``) → **block**. Short bodies
       alone are *not* enough — many category index pages legitimately
       have very little text until you click through.
    3. Otherwise → **not a block**.
    """
    if not html:
        return BlockVerdict(is_block=False)

    low = html.lower()

    # Rule 1 — explicit blocker keyword.
    for kw in _BLOCK_KEYWORDS:
        if kw in low:
            # Clip ~60 chars around the hit for the error trail.
            idx = low.find(kw)
            start = max(0, idx - 20)
            end = min(len(html), idx + len(kw) + 20)
            evidence = html[start:end].replace("\n", " ").strip()
            return BlockVerdict(
                is_block=True,
                signal=f"keyword:{kw}",
                evidence=evidence,
            )

    # Rule 2 — short body with a soft-block indicator.
    text = _strip_tags(html)
    if len(text) < _SHORT_BODY_CHARS:
        soft_indicators = ("blocked", "captcha", "forbidden", "denied", "unusual traffic")
        for kw in soft_indicators:
            if kw in low:
                return BlockVerdict(
                    is_block=True,
                    signal=f"short-body+keyword:{kw}",
                    evidence=text[:100],
                )

    return BlockVerdict(is_block=False)


__all__ = ["BlockVerdict", "detect_block"]
