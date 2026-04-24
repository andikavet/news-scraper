"""Categorization package.

Iter 2 shipped ``rules.py`` (CSV/Excel import/export).
Iter 5 added ``engine.py`` — token-matching + multi-category explosion.
Iter 6 adds ``pivot.py`` — Source × Category pivot with full-category reindex.
"""

from categorizer.engine import (
    GROUPING_COLUMNS,
    RAW_COLUMNS,
    categorize_all_groupings,
    categorize_items_to_frame,
    is_globally_excluded,
    items_to_raw_dataframe,
    matches_for_title,
    normalize,
    rule_matches,
)
from categorizer.pivot import (
    PIVOT_TOTAL_COL,
    PIVOT_TOTAL_ROW,
    build_all_pivots,
    build_pivot,
)
from categorizer.rules import (
    rules_from_csv,
    rules_from_dataframe,
    rules_from_editor_dataframe,
    rules_from_excel,
    rules_to_dataframe,
)

__all__ = [
    "GROUPING_COLUMNS",
    "PIVOT_TOTAL_COL",
    "PIVOT_TOTAL_ROW",
    "RAW_COLUMNS",
    "build_all_pivots",
    "build_pivot",
    "categorize_all_groupings",
    "categorize_items_to_frame",
    "is_globally_excluded",
    "items_to_raw_dataframe",
    "matches_for_title",
    "normalize",
    "rule_matches",
    "rules_from_csv",
    "rules_from_dataframe",
    "rules_from_editor_dataframe",
    "rules_from_excel",
    "rules_to_dataframe",
]
