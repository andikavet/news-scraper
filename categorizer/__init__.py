"""Categorization package.

Iter 2 shipped ``rules.py`` (CSV/Excel import/export).
Iter 5 adds ``engine.py`` — the actual token-matching + multi-category
explosion logic that powers the Main Dashboard results tabs.
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
from categorizer.rules import (
    rules_from_csv,
    rules_from_dataframe,
    rules_from_editor_dataframe,
    rules_from_excel,
    rules_to_dataframe,
)

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
    "rules_from_csv",
    "rules_from_dataframe",
    "rules_from_editor_dataframe",
    "rules_from_excel",
    "rules_to_dataframe",
]
