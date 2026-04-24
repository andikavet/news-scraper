"""Categorization engine — maps scraped items into grouping-scoped frames.

Pure functions (no Streamlit / no I/O) so the whole module is headless-testable.

Matching semantics (per PRD §4.3):
- Normalize the title: lowercase, strip accents, replace any non-alphanumeric
  character with a single space.
- For each rule, a **category hit** requires:
    * at least one ``include_token`` to match (logical OR across includes), AND
    * no ``exclude_token`` to match (logical AND across excludes).
- A rule with an empty ``include_tokens`` list never matches — no positive
  signal means no category assignment. Keeping this strict avoids the
  "empty-rule grabs everything" footgun.
- Tokens are whitespace-sensitive phrases: "harga minyak" matches only when
  those two words appear consecutively as a word-boundary phrase. Single-word
  tokens match on word boundaries too, so "agri" does NOT match "agriculture"
  but DOES match "sektor agri".
- Global exclude tokens (from ``AppSettings.overall_exclude_tokens``) drop the
  entire item from every grouping frame before categorization runs. The raw
  table is left untouched so you can see what was filtered.

Multi-category explosion:
    If one article matches N rules in a single grouping, the returned frame
    contains N rows for that article (one per matched category).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

import pandas as pd

from config import CategorizerGrouping, CategoryRule
from scraper.models import NewsItem

# --------------------------------------------------------------------------- #
# Normalization + token matching
# --------------------------------------------------------------------------- #

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize(text: str) -> str:
    """Lower-case, strip accents, collapse punctuation/whitespace into single spaces.

    Output always starts and ends with a space so naive ``" token "`` checks
    work at frame boundaries — but we still prefer the regex word-boundary
    variant below because it's more precise.
    """
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_only.lower()
    cleaned = _NON_ALNUM.sub(" ", lowered).strip()
    return cleaned


def _token_matches(normalized_text: str, raw_token: str) -> bool:
    """Return True if ``raw_token`` appears as a whole-word match in the text.

    The token itself is normalized the same way as the text, so casing,
    punctuation, and accent differences between the rule config and the
    scraped title all wash out.
    """
    tnorm = normalize(raw_token)
    if not tnorm:
        return False
    return re.search(rf"\b{re.escape(tnorm)}\b", normalized_text) is not None


def _any_token_matches(normalized_text: str, tokens: Iterable[str]) -> bool:
    return any(_token_matches(normalized_text, t) for t in tokens)


# --------------------------------------------------------------------------- #
# Rule + grouping matching
# --------------------------------------------------------------------------- #


def rule_matches(normalized_title: str, rule: CategoryRule) -> bool:
    """True iff the rule considers ``normalized_title`` to be its category."""
    if not rule.include_tokens:
        # No positive signal → rule never matches.
        return False
    if not _any_token_matches(normalized_title, rule.include_tokens):
        return False
    return not _any_token_matches(normalized_title, rule.exclude_tokens)


def matches_for_title(title: str, grouping: CategorizerGrouping) -> list[str]:
    """Return every category in this grouping that matches ``title``.

    Order mirrors the grouping's rule order so downstream rendering is
    deterministic.
    """
    t = normalize(title)
    return [rule.category for rule in grouping.rules if rule_matches(t, rule)]


# --------------------------------------------------------------------------- #
# Item filtering (global excludes)
# --------------------------------------------------------------------------- #


def is_globally_excluded(title: str, global_excludes: Iterable[str]) -> bool:
    """Check whether any ``overall_exclude_tokens`` token appears in the title.

    Empty / missing token lists are a no-op (never excludes).
    """
    if not global_excludes:
        return False
    return _any_token_matches(normalize(title), global_excludes)


# --------------------------------------------------------------------------- #
# DataFrame builders
# --------------------------------------------------------------------------- #

RAW_COLUMNS = ["Date", "Source", "Title", "Link", "Page"]
GROUPING_COLUMNS = ["Category", "Date", "Source", "Title", "Link", "Page"]


def _format_date(item: NewsItem) -> str:
    """PRD §4.2 — standardise on DD-MM-YYYY; fall back to raw for undated items."""
    if item.date_parsed is None:
        return item.date_raw or ""
    return item.date_parsed.strftime("%d-%m-%Y")


def _empty_frame(columns: list[str]) -> pd.DataFrame:
    """Always return an empty frame with the expected string-typed columns.

    Needed because Streamlit's ``st.data_editor`` gets upset when an empty
    frame defaults its columns to ``float64``.
    """
    return pd.DataFrame({c: pd.Series([], dtype="string") for c in columns})


def items_to_raw_dataframe(items: list[NewsItem]) -> pd.DataFrame:
    """Un-exploded read-only table of every scraped item (section D.1).

    Global exclude tokens are intentionally NOT applied here — this frame is
    for auditing "what was scraped", not "what categorized".
    """
    if not items:
        return _empty_frame(RAW_COLUMNS)
    rows = [
        {
            "Date": _format_date(it),
            "Source": it.source,
            "Title": it.title,
            "Link": it.link,
            "Page": it.page,
        }
        for it in items
    ]
    df = pd.DataFrame(rows, columns=RAW_COLUMNS)
    # Page is numeric; keep the rest as string for st.data_editor friendliness.
    for col in ("Date", "Source", "Title", "Link"):
        df[col] = df[col].astype("string")
    return df


def categorize_items_to_frame(
    items: list[NewsItem],
    grouping: CategorizerGrouping,
    global_excludes: Iterable[str] = (),
) -> pd.DataFrame:
    """Explode matched items into a per-grouping frame.

    One row per ``(item × matched category)``. Items matching zero rules in
    this grouping are omitted (the raw table still shows them). Items whose
    title triggers a global exclude token are dropped before matching.
    """
    rows: list[dict[str, object]] = []
    excludes_list = list(global_excludes)
    for it in items:
        if is_globally_excluded(it.title, excludes_list):
            continue
        for category in matches_for_title(it.title, grouping):
            rows.append(
                {
                    "Category": category,
                    "Date": _format_date(it),
                    "Source": it.source,
                    "Title": it.title,
                    "Link": it.link,
                    "Page": it.page,
                }
            )
    if not rows:
        return _empty_frame(GROUPING_COLUMNS)
    df = pd.DataFrame(rows, columns=GROUPING_COLUMNS)
    for col in ("Category", "Date", "Source", "Title", "Link"):
        df[col] = df[col].astype("string")
    return df


def categorize_all_groupings(
    items: list[NewsItem],
    groupings: list[CategorizerGrouping],
    global_excludes: Iterable[str] = (),
) -> dict[str, pd.DataFrame]:
    """Convenience: produce one exploded frame per grouping, keyed by name."""
    excludes_list = list(global_excludes)
    return {g.name: categorize_items_to_frame(items, g, excludes_list) for g in groupings}


__all__ = [
    "GROUPING_COLUMNS",
    "RAW_COLUMNS",
    "categorize_all_groupings",
    "categorize_items_to_frame",
    "is_globally_excluded",
    "items_to_raw_dataframe",
    "matches_for_title",
    "normalize",
    "rule_matches",
]
