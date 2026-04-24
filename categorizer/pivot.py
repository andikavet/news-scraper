"""Pivot-table builder — Source × Category counts per grouping.

Pure Python / pandas (no Streamlit, no I/O) so it stays headless-testable.

PRD §4.4 — the pivot must show **every** configured category for a grouping,
even if zero items matched that category. We achieve this by reindexing the
pivot's columns on the full ordered list of categories from the grouping
config before returning. Rows (sources) are only the sources that actually
appear in the data — zero-content *sources* don't clutter the pivot, but
zero-content *categories* still show because the PRD calls that out.

The pivot input is the **exploded** per-grouping frame produced by
``categorizer.engine.categorize_items_to_frame`` (or the edited version of
it coming out of the Iter 6 ``st.data_editor``), so one article that matched
two categories already contributes two rows and therefore counts once in each
category column. That's the correct behaviour.
"""

from __future__ import annotations

import pandas as pd

from config import CategorizerGrouping

PIVOT_TOTAL_COL = "Total"
PIVOT_TOTAL_ROW = "Total"


def _category_order(grouping: CategorizerGrouping) -> list[str]:
    """Return the grouping's category names in declaration order, unique."""
    seen: set[str] = set()
    order: list[str] = []
    for rule in grouping.rules:
        if rule.category not in seen:
            seen.add(rule.category)
            order.append(rule.category)
    return order


def build_pivot(
    exploded_frame: pd.DataFrame,
    grouping: CategorizerGrouping,
) -> pd.DataFrame:
    """Build a Source × Category count pivot.

    - Columns are reindexed on the full category list from ``grouping.rules``
      so zero-match categories still appear as a column of 0s.
    - A final ``Total`` column sums each row; a final ``Total`` row sums each
      column. The bottom-right cell is the grand total.
    - If there are no rows in the input, returns an empty-row frame with the
      full category columns + ``Total`` column so the UI can still render a
      "zero matches across N categories" header meaningfully.
    """
    categories = _category_order(grouping)
    if not categories:
        # No rules configured → empty pivot with just the metadata columns.
        return pd.DataFrame({"Source": pd.Series([], dtype="string")}).set_index("Source")

    if exploded_frame.empty or "Category" not in exploded_frame.columns:
        empty = pd.DataFrame(
            0,
            index=pd.Index([], name="Source"),
            columns=categories,
            dtype="int64",
        )
        empty[PIVOT_TOTAL_COL] = pd.Series([], dtype="int64")
        return empty

    # One row per (item × matched category) already, so a simple crosstab
    # gives us the Source × Category counts directly.
    crosstab = pd.crosstab(
        index=exploded_frame["Source"],
        columns=exploded_frame["Category"],
    )
    # Reindex columns to force every configured category to appear, in order.
    pivot = crosstab.reindex(columns=categories, fill_value=0).astype("int64")
    pivot.index.name = "Source"
    pivot[PIVOT_TOTAL_COL] = pivot.sum(axis=1).astype("int64")

    totals_row = pivot.sum(axis=0).to_frame().T.astype("int64")
    totals_row.index = pd.Index([PIVOT_TOTAL_ROW], name="Source")
    pivot = pd.concat([pivot, totals_row], axis=0)
    return pivot


def build_all_pivots(
    exploded_frames: dict[str, pd.DataFrame],
    groupings: list[CategorizerGrouping],
) -> dict[str, pd.DataFrame]:
    """Convenience: one pivot per grouping, keyed by grouping name."""
    by_name = {g.name: g for g in groupings}
    return {
        name: build_pivot(frame, by_name[name])
        for name, frame in exploded_frames.items()
        if name in by_name
    }


__all__ = [
    "PIVOT_TOTAL_COL",
    "PIVOT_TOTAL_ROW",
    "build_all_pivots",
    "build_pivot",
]
