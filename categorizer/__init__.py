"""Categorization package.

Iter 2 shipped ``rules.py`` (CSV/Excel import/export).
Iter 5 added ``engine.py`` — token-matching + multi-category explosion.
Iter 6 added ``pivot.py`` — Source × Category numeric pivot. That has
been replaced (Iter 13) by a 2-way Category × Month aggregation with
numbered-list cell strings. Iter 14 generalized the builder to support
both monthly and quarterly periods via a ``period=`` kwarg; see
:mod:`categorizer.pivot` for details.
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
    COLUMN_LEVEL_NAMES,
    INDEX_NAME,
    INDONESIAN_MONTHS,
    QUARTER_COLUMN_LEVEL_NAMES,
    SUBCOLUMNS,
    Period,
    aggregation_to_html,
    build_aggregation,
    build_all_aggregations,
    month_label,
    numbered_list,
    quarter_label,
    quarter_of_month,
)
from categorizer.rules import (
    rules_from_csv,
    rules_from_dataframe,
    rules_from_editor_dataframe,
    rules_from_excel,
    rules_to_dataframe,
)

__all__ = [
    "COLUMN_LEVEL_NAMES",
    "GROUPING_COLUMNS",
    "INDEX_NAME",
    "INDONESIAN_MONTHS",
    "Period",
    "QUARTER_COLUMN_LEVEL_NAMES",
    "RAW_COLUMNS",
    "SUBCOLUMNS",
    "aggregation_to_html",
    "build_aggregation",
    "build_all_aggregations",
    "categorize_all_groupings",
    "categorize_items_to_frame",
    "is_globally_excluded",
    "items_to_raw_dataframe",
    "matches_for_title",
    "month_label",
    "normalize",
    "numbered_list",
    "quarter_label",
    "quarter_of_month",
    "rule_matches",
    "rules_from_csv",
    "rules_from_dataframe",
    "rules_from_editor_dataframe",
    "rules_from_excel",
    "rules_to_dataframe",
]
