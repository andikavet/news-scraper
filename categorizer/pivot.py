"""2-way Category × Period aggregation builder (monthly + quarterly).

The leftmost column is the **Category** index (every category from the
grouping's rules, sorted ascending — even when no data matches). The
columns are a 2-level ``MultiIndex`` of ``(Period, [Title, Link, Date])``
where periods are derived from the data and sorted chronologically.

Two period modes share the same builder:

- ``period="month"`` (default) — top-level labels are Indonesian month
  names plus the year, e.g. ``Januari 2026``, ``Februari 2026``.
- ``period="quarter"`` — labels are ``Q1-2026``, ``Q2-2026``, …
  Quarters map calendar months 1-3 → Q1, 4-6 → Q2, 7-9 → Q3, 10-12 → Q4.

Cells are strings formatted as numbered lists separated by ``\\n`` —
e.g. a 'Title' cell with two articles::

    1. First Article Title
    2. Second Article Title

The matching ``Link`` cell holds ``1. https://...\\n2. https://...``.

Pure pandas / pure Python — no Streamlit, no I/O — so the module stays
headless-testable.

Input contract: ``exploded_frame`` is the per-grouping frame produced by
:func:`categorizer.engine.categorize_items_to_frame` (or the edited
version coming out of the ``st.data_editor``), which has columns
``Category, Date, Source, Title, Link, Page``. ``Date`` is a string in
``DD-MM-YYYY`` form (``categorizer.engine._format_date``); rows whose
date doesn't parse against that format are silently dropped from the
aggregation — they have no period bucket. The Raw Data tab still shows
them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

import pandas as pd

from config import CategorizerGrouping

#: Indonesian month names used as the top-level column header label
#: when ``period="month"``.
INDONESIAN_MONTHS: dict[int, str] = {
    1: "Januari",
    2: "Februari",
    3: "Maret",
    4: "April",
    5: "Mei",
    6: "Juni",
    7: "Juli",
    8: "Agustus",
    9: "September",
    10: "Oktober",
    11: "November",
    12: "Desember",
}

#: Bottom-level sub-columns under each Period header.
SUBCOLUMNS: list[str] = ["Title", "Link", "Date"]

#: Default top-level MultiIndex name for ``period="month"``.
COLUMN_LEVEL_NAMES: tuple[str, str] = ("Month", "Field")

#: Default top-level MultiIndex name for ``period="quarter"``.
QUARTER_COLUMN_LEVEL_NAMES: tuple[str, str] = ("Quarter", "Field")

#: Index name (the leftmost column on the rendered table).
INDEX_NAME: str = "Category"

#: Accepted period modes.
Period = Literal["month", "quarter"]


def _all_categories_sorted(grouping: CategorizerGrouping) -> list[str]:
    """All categories defined in the grouping's rules, sorted ascending.

    Duplicates are de-duplicated; empty / blank category names are dropped.
    Sort is plain alphabetical (case-sensitive Python default) so it stays
    deterministic regardless of the user's locale.
    """
    seen: set[str] = set()
    for rule in grouping.rules:
        cat = (rule.category or "").strip()
        if cat:
            seen.add(cat)
    return sorted(seen)


def _parse_dd_mm_yyyy(date_str: object) -> datetime | None:
    """Parse ``DD-MM-YYYY`` (the format ``engine._format_date`` emits).

    Returns ``None`` for missing / unparseable values; those rows are
    dropped from the aggregation rather than placed in a synthetic
    bucket — the spec says the column axis "expands horizontally based
    on the available data" so we don't invent a "(unknown date)" header.
    """
    if not isinstance(date_str, str):
        return None
    try:
        return datetime.strptime(date_str.strip(), "%d-%m-%Y")
    except ValueError:
        return None


def month_label(dt: datetime) -> str:
    """Indonesian-month + year, e.g. ``Januari 2026``."""
    return f"{INDONESIAN_MONTHS[dt.month]} {dt.year}"


def quarter_of_month(month: int) -> int:
    """Map calendar month (1-12) → quarter (1-4).

    Jan/Feb/Mar → 1, Apr/May/Jun → 2, Jul/Aug/Sep → 3, Oct/Nov/Dec → 4.
    """
    if not 1 <= month <= 12:
        raise ValueError(f"month must be between 1 and 12, got {month}")
    return (month - 1) // 3 + 1


def quarter_label(dt: datetime) -> str:
    """Quarter-year label, e.g. ``Q1-2026`` for January-March 2026."""
    return f"Q{quarter_of_month(dt.month)}-{dt.year}"


def _period_label(dt: datetime, period: Period) -> str:
    if period == "quarter":
        return quarter_label(dt)
    return month_label(dt)


def _period_sort_key(dt: datetime, period: Period) -> tuple[int, int]:
    """Sortable tuple for chronological ordering within the chosen period."""
    if period == "quarter":
        return (dt.year, quarter_of_month(dt.month))
    return (dt.year, dt.month)


def _period_level_names(period: Period) -> tuple[str, str]:
    if period == "quarter":
        return QUARTER_COLUMN_LEVEL_NAMES
    return COLUMN_LEVEL_NAMES


def numbered_list(values: list[str]) -> str:
    """Join values as ``1. v1\\n2. v2\\n…``. Empty list → empty string."""
    if not values:
        return ""
    return "\n".join(f"{i + 1}. {v}" for i, v in enumerate(values))


def _empty_aggregation(categories: list[str], period: Period) -> pd.DataFrame:
    """Frame with the full category index but no period columns."""
    return pd.DataFrame(
        index=pd.Index(categories, name=INDEX_NAME),
        columns=pd.MultiIndex.from_tuples([], names=list(_period_level_names(period))),
        dtype="object",
    )


def build_aggregation(
    exploded_frame: pd.DataFrame,
    grouping: CategorizerGrouping,
    *,
    period: Period = "month",
) -> pd.DataFrame:
    """Build the 2-way ``Category × MultiIndex(Period, Field)`` aggregation.

    - Every category from ``grouping.rules`` is present as a row, sorted
      ascending, regardless of whether any item matched.
    - Periods are derived from the ``Date`` column (``DD-MM-YYYY``) and
      sorted chronologically. Rows with unparseable / missing dates are
      omitted from this view (they remain visible in Raw Data).
    - Cells are strings of numbered lists; empty cells are ``""``.

    ``period`` toggles between monthly (``"month"``, Indonesian month
    names) and quarterly (``"quarter"``, ``Q1-YYYY`` labels). Every other
    constraint — full-category index, chronological period order,
    numbered-list cell format — is identical across the two modes.

    A grouping with no rules returns an empty frame (no rows, no cols).
    """
    if period not in ("month", "quarter"):
        raise ValueError(f"period must be 'month' or 'quarter', got {period!r}")

    categories = _all_categories_sorted(grouping)
    level_names = _period_level_names(period)
    if not categories:
        return _empty_aggregation([], period)

    if exploded_frame.empty or "Category" not in exploded_frame.columns:
        return _empty_aggregation(categories, period)

    df = exploded_frame.copy()
    df["_dt"] = df["Date"].apply(_parse_dd_mm_yyyy)
    df = df.dropna(subset=["_dt"])
    if df.empty:
        return _empty_aggregation(categories, period)

    df["_period_label"] = df["_dt"].apply(lambda d: _period_label(d, period))
    df["_sort_key"] = df["_dt"].apply(lambda d: _period_sort_key(d, period))

    period_order = (
        df[["_period_label", "_sort_key"]]
        .drop_duplicates("_period_label")
        .sort_values("_sort_key")["_period_label"]
        .tolist()
    )

    columns = pd.MultiIndex.from_product([period_order, SUBCOLUMNS], names=list(level_names))
    out = pd.DataFrame(
        "",
        index=pd.Index(categories, name=INDEX_NAME),
        columns=columns,
        dtype="object",
    )

    grouped = df.groupby(["Category", "_period_label"], sort=False)
    for (cat, bucket), sub in grouped:
        if cat not in categories:
            # An edited row with a category not in the grouping rules.
            # We honour the rules-based row index rather than the data,
            # so such rows are silently skipped.
            continue
        sub_sorted = sub.sort_values("_dt", kind="stable")
        out.loc[cat, (bucket, "Title")] = numbered_list(sub_sorted["Title"].astype(str).tolist())
        out.loc[cat, (bucket, "Link")] = numbered_list(sub_sorted["Link"].astype(str).tolist())
        out.loc[cat, (bucket, "Date")] = numbered_list(sub_sorted["Date"].astype(str).tolist())

    return out


def build_all_aggregations(
    exploded_frames: dict[str, pd.DataFrame],
    groupings: list[CategorizerGrouping],
    *,
    period: Period = "month",
) -> dict[str, pd.DataFrame]:
    """One aggregation per grouping, keyed by grouping name.

    Passes ``period`` through to :func:`build_aggregation` so callers can
    build a bundle of monthly or quarterly frames in one call.
    """
    by_name = {g.name: g for g in groupings}
    return {
        name: build_aggregation(frame, by_name[name], period=period)
        for name, frame in exploded_frames.items()
        if name in by_name
    }


def aggregation_to_html(df: pd.DataFrame) -> str:
    """Convert an aggregation frame to HTML that respects ``\\n``.

    The default ``df.to_html`` output collapses newlines visually because
    HTML treats whitespace as a single space. We pair the un-escaped HTML
    with a wrapper ``<div>`` that has CSS ``white-space: pre-wrap``,
    which preserves both spaces and line breaks. The whole snippet is
    safe to drop into ``st.markdown(..., unsafe_allow_html=True)``.

    Keeping the HTML build out of the Streamlit module means the renderer
    is testable and the markup stays consistent across call sites
    (dashboard, exports, future PDF view, …).
    """
    if df.empty or len(df.columns) == 0:
        return ""
    table_html = df.to_html(escape=True, na_rep="", border=0)
    css = (
        "<style>"
        ".aggregation-wrapper table {"
        " border-collapse: collapse; width: 100%; font-size: 0.88rem; }"
        ".aggregation-wrapper th, .aggregation-wrapper td {"
        " border: 1px solid rgba(128,128,128,0.3); padding: 6px 8px;"
        " vertical-align: top; text-align: left;"
        " white-space: pre-wrap; word-break: break-word; }"
        ".aggregation-wrapper thead th {"
        " background: rgba(128,128,128,0.12);"
        " position: sticky; top: 0; z-index: 1; }"
        ".aggregation-wrapper tbody th {"
        " font-weight: 600; background: rgba(128,128,128,0.05); }"
        ".aggregation-wrapper { max-height: 540px; overflow: auto;"
        " border: 1px solid rgba(128,128,128,0.25); border-radius: 4px; }"
        "</style>"
    )
    return css + f'<div class="aggregation-wrapper">{table_html}</div>'


__all__ = [
    "COLUMN_LEVEL_NAMES",
    "INDEX_NAME",
    "INDONESIAN_MONTHS",
    "Period",
    "QUARTER_COLUMN_LEVEL_NAMES",
    "SUBCOLUMNS",
    "aggregation_to_html",
    "build_aggregation",
    "build_all_aggregations",
    "month_label",
    "numbered_list",
    "quarter_label",
    "quarter_of_month",
]
