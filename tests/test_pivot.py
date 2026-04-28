"""Unit tests for the Iter 13 2-way Category × Month aggregation builder.

The Iter 6 numeric Source × Category pivot was replaced by a string-valued
``Category × MultiIndex(Month, [Title, Link, Date])`` aggregation. These
tests pin the new shape's invariants:

- Every category from the grouping rules is present as a row, sorted
  ascending, even when no item matched it.
- Columns are a 2-level ``MultiIndex(Month, [Title, Link, Date])`` where
  the months are derived from the data and ordered chronologically.
- Cell values are strings of numbered lists separated by ``\\n``.
- The HTML renderer respects ``\\n`` via ``white-space: pre-wrap`` CSS.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from categorizer.engine import categorize_items_to_frame
from categorizer.pivot import (
    COLUMN_LEVEL_NAMES,
    INDEX_NAME,
    INDONESIAN_MONTHS,
    QUARTER_COLUMN_LEVEL_NAMES,
    SUBCOLUMNS,
    aggregation_to_html,
    build_aggregation,
    build_all_aggregations,
    month_label,
    numbered_list,
    quarter_label,
    quarter_of_month,
)
from config import CategorizerGrouping, CategoryRule
from scraper.models import NewsItem


def _rule(category: str, include: list[str]) -> CategoryRule:
    return CategoryRule(category=category, include_tokens=include)


def _grouping(name: str, rules: list[CategoryRule]) -> CategorizerGrouping:
    return CategorizerGrouping(name=name, rules=rules)


def _item(
    title: str,
    *,
    source: str = "PortalA",
    page: int = 1,
    date_parsed: datetime | None = None,
    date_raw: str = "",
) -> NewsItem:
    return NewsItem(
        title=title,
        link=f"https://example.com/{title.replace(' ', '-').lower()}",
        date_raw=date_raw or (date_parsed.strftime("%d %b %Y") if date_parsed else ""),
        date_parsed=date_parsed,
        source=source,
        page=page,
    )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def test_numbered_list_format() -> None:
    assert numbered_list([]) == ""
    assert numbered_list(["alpha"]) == "1. alpha"
    assert numbered_list(["alpha", "beta", "gamma"]) == "1. alpha\n2. beta\n3. gamma"


def test_month_label_uses_indonesian_names() -> None:
    assert month_label(datetime(2026, 1, 15)) == "Januari 2026"
    assert month_label(datetime(2026, 12, 31)) == "Desember 2026"
    # Each month constant individually.
    for n, name in INDONESIAN_MONTHS.items():
        assert month_label(datetime(2026, n, 1)) == f"{name} 2026"


# --------------------------------------------------------------------------- #
# Row index: every category, sorted ascending, even with no data
# --------------------------------------------------------------------------- #


def test_all_categories_present_sorted_ascending_even_with_zero_matches() -> None:
    grouping = _grouping(
        "Sektor",
        [
            # Declaration order is Energi, Agri, Tambang — but the row index
            # must be sorted ascending alphabetically. Tambang has no
            # matching item below.
            _rule("Energi", ["bbm"]),
            _rule("Agri", ["pertanian"]),
            _rule("Tambang", ["tambang"]),
        ],
    )
    items = [
        _item("Harga BBM naik", date_parsed=datetime(2026, 1, 10)),
        _item("Produksi pertanian stabil", date_parsed=datetime(2026, 1, 20)),
    ]
    frame = categorize_items_to_frame(items, grouping)

    agg = build_aggregation(frame, grouping)

    # Sorted ascending alphabetical — NOT declaration order.
    assert list(agg.index) == ["Agri", "Energi", "Tambang"]
    assert agg.index.name == INDEX_NAME
    # Tambang row exists; each of its cells is empty string.
    assert all(agg.loc["Tambang", col] == "" for col in agg.columns)


def test_empty_frame_keeps_all_categories_with_no_month_columns() -> None:
    grouping = _grouping(
        "Sektor",
        [_rule("Agri", ["pertanian"]), _rule("Energi", ["bbm"])],
    )
    empty = categorize_items_to_frame([], grouping)

    agg = build_aggregation(empty, grouping)

    assert list(agg.index) == ["Agri", "Energi"]
    assert len(agg.columns) == 0  # no months in data → no month columns
    assert agg.columns.names == list(COLUMN_LEVEL_NAMES)


def test_grouping_with_no_rules_returns_empty_frame() -> None:
    grouping = _grouping("Empty", [])
    frame = pd.DataFrame(columns=["Category", "Date", "Source", "Title", "Link", "Page"])

    agg = build_aggregation(frame, grouping)

    assert agg.empty
    assert list(agg.columns) == []


# --------------------------------------------------------------------------- #
# Column structure: MultiIndex(Month, [Title, Link, Date]), chronological
# --------------------------------------------------------------------------- #


def test_columns_are_multiindex_with_three_subcolumns_per_month() -> None:
    grouping = _grouping("Sektor", [_rule("Agri", ["pertanian"])])
    items = [_item("Pertanian Jan", date_parsed=datetime(2026, 1, 5))]
    frame = categorize_items_to_frame(items, grouping)

    agg = build_aggregation(frame, grouping)

    assert agg.columns.nlevels == 2
    assert agg.columns.names == list(COLUMN_LEVEL_NAMES)
    months = agg.columns.get_level_values("Month").unique().tolist()
    assert months == ["Januari 2026"]
    fields = agg.columns.get_level_values("Field").tolist()
    assert fields == SUBCOLUMNS


def test_months_are_ordered_chronologically_not_alphabetically() -> None:
    """Februari < Maret < Januari alphabetically, but chronological order wins."""
    grouping = _grouping("Sektor", [_rule("Agri", ["pertanian"])])
    items = [
        _item("Pertanian Mar", date_parsed=datetime(2026, 3, 1)),
        _item("Pertanian Jan", date_parsed=datetime(2026, 1, 1)),
        _item("Pertanian Feb", date_parsed=datetime(2026, 2, 1)),
    ]
    frame = categorize_items_to_frame(items, grouping)

    agg = build_aggregation(frame, grouping)

    months = agg.columns.get_level_values("Month").unique().tolist()
    assert months == ["Januari 2026", "Februari 2026", "Maret 2026"]


def test_year_boundary_orders_chronologically() -> None:
    grouping = _grouping("Sektor", [_rule("Agri", ["pertanian"])])
    items = [
        _item("Pertanian Jan 2026", date_parsed=datetime(2026, 1, 5)),
        _item("Pertanian Dec 2025", date_parsed=datetime(2025, 12, 25)),
    ]
    frame = categorize_items_to_frame(items, grouping)

    agg = build_aggregation(frame, grouping)

    months = agg.columns.get_level_values("Month").unique().tolist()
    assert months == ["Desember 2025", "Januari 2026"]


# --------------------------------------------------------------------------- #
# Cell content: numbered lists with `\n` separators
# --------------------------------------------------------------------------- #


def test_cells_are_numbered_lists_with_newline_separators() -> None:
    grouping = _grouping("Sektor", [_rule("Agri", ["pertanian"])])
    items = [
        _item(
            "First Article",
            date_parsed=datetime(2026, 1, 5),
        ),
        _item(
            "Second Article",
            date_parsed=datetime(2026, 1, 20),
        ),
    ]
    items[0] = NewsItem(
        title="First Article: pertanian naik",
        link="https://link1.com",
        date_raw="",
        date_parsed=datetime(2026, 1, 5),
        source="PortalA",
        page=1,
    )
    items[1] = NewsItem(
        title="Second Article: pertanian stabil",
        link="https://link2.com",
        date_raw="",
        date_parsed=datetime(2026, 1, 20),
        source="PortalA",
        page=1,
    )
    frame = categorize_items_to_frame(items, grouping)

    agg = build_aggregation(frame, grouping)

    title_cell = agg.loc["Agri", ("Januari 2026", "Title")]
    link_cell = agg.loc["Agri", ("Januari 2026", "Link")]
    date_cell = agg.loc["Agri", ("Januari 2026", "Date")]

    assert title_cell == ("1. First Article: pertanian naik\n2. Second Article: pertanian stabil")
    assert link_cell == "1. https://link1.com\n2. https://link2.com"
    # Dates are the engine-formatted DD-MM-YYYY strings.
    assert date_cell == "1. 05-01-2026\n2. 20-01-2026"


def test_single_item_cell_is_a_one_element_numbered_list() -> None:
    grouping = _grouping("Sektor", [_rule("Agri", ["pertanian"])])
    items = [_item("Pertanian solo", date_parsed=datetime(2026, 4, 1))]
    frame = categorize_items_to_frame(items, grouping)

    agg = build_aggregation(frame, grouping)

    assert agg.loc["Agri", ("April 2026", "Title")] == "1. Pertanian solo"


def test_cells_for_uncovered_category_or_month_are_empty_strings() -> None:
    grouping = _grouping(
        "Sektor",
        [_rule("Agri", ["pertanian"]), _rule("Energi", ["bbm"])],
    )
    # Only Agri has data, only in Februari.
    items = [_item("Pertanian Feb", date_parsed=datetime(2026, 2, 1))]
    frame = categorize_items_to_frame(items, grouping)

    agg = build_aggregation(frame, grouping)

    assert agg.loc["Energi", ("Februari 2026", "Title")] == ""
    assert agg.loc["Energi", ("Februari 2026", "Link")] == ""
    assert agg.loc["Energi", ("Februari 2026", "Date")] == ""


def test_undated_items_are_dropped_from_aggregation() -> None:
    """An item whose date can't be parsed has no month bucket — silently omitted."""
    grouping = _grouping("Sektor", [_rule("Agri", ["pertanian"])])
    items = [
        _item("Pertanian Jan", date_parsed=datetime(2026, 1, 5)),
        _item("Pertanian undated", date_raw="not a date"),
    ]
    frame = categorize_items_to_frame(items, grouping)

    agg = build_aggregation(frame, grouping)

    cell = agg.loc["Agri", ("Januari 2026", "Title")]
    # Only the dated item appears.
    assert cell == "1. Pertanian Jan"


# --------------------------------------------------------------------------- #
# Multi-source aggregation collapses across sources (no Source axis)
# --------------------------------------------------------------------------- #


def test_items_from_multiple_sources_collapse_into_same_category_month_cell() -> None:
    grouping = _grouping("Sektor", [_rule("Agri", ["pertanian"])])
    items = [
        NewsItem(
            title="A: pertanian",
            link="https://a.example.com/x",
            date_raw="",
            date_parsed=datetime(2026, 1, 5),
            source="PortalA",
            page=1,
        ),
        NewsItem(
            title="B: pertanian",
            link="https://b.example.com/x",
            date_raw="",
            date_parsed=datetime(2026, 1, 6),
            source="PortalB",
            page=1,
        ),
    ]
    frame = categorize_items_to_frame(items, grouping)

    agg = build_aggregation(frame, grouping)

    cell = agg.loc["Agri", ("Januari 2026", "Title")]
    assert "1. A: pertanian" in cell
    assert "2. B: pertanian" in cell
    assert cell.count("\n") == 1  # exactly one separator between two items


# --------------------------------------------------------------------------- #
# build_all_aggregations
# --------------------------------------------------------------------------- #


def test_build_all_aggregations_keyed_by_grouping_name() -> None:
    g1 = _grouping("Sektor", [_rule("Agri", ["pertanian"])])
    g2 = _grouping("Pengeluaran", [_rule("Konsumsi", ["konsumsi"])])
    items = [
        _item("Konsumsi rumah tangga naik", date_parsed=datetime(2026, 2, 1)),
        _item("Produksi pertanian stabil", date_parsed=datetime(2026, 2, 2)),
    ]
    frames = {
        "Sektor": categorize_items_to_frame(items, g1),
        "Pengeluaran": categorize_items_to_frame(items, g2),
    }

    aggregations = build_all_aggregations(frames, [g1, g2])

    assert set(aggregations.keys()) == {"Sektor", "Pengeluaran"}
    assert (
        "1. Produksi pertanian stabil"
        in aggregations["Sektor"].loc["Agri", ("Februari 2026", "Title")]
    )
    assert (
        "1. Konsumsi rumah tangga naik"
        in aggregations["Pengeluaran"].loc["Konsumsi", ("Februari 2026", "Title")]
    )


# --------------------------------------------------------------------------- #
# Edited-frame paths (Update Aggregation button)
# --------------------------------------------------------------------------- #


def test_edited_frame_with_unknown_category_is_silently_skipped() -> None:
    """Index is rules-based; an edited row whose Category isn't in the grouping is dropped."""
    grouping = _grouping("Sektor", [_rule("Agri", ["pertanian"])])
    edited_frame = pd.DataFrame(
        [
            {
                "Category": "Agri",
                "Date": "05-01-2026",
                "Source": "PortalA",
                "Title": "Pertanian valid",
                "Link": "https://example.com/x",
                "Page": 1,
            },
            {
                "Category": "InvasiveCategory",  # not in grouping rules
                "Date": "05-01-2026",
                "Source": "PortalA",
                "Title": "Should not appear",
                "Link": "https://example.com/y",
                "Page": 1,
            },
        ]
    )

    agg = build_aggregation(edited_frame, grouping)

    assert list(agg.index) == ["Agri"]
    cell = agg.loc["Agri", ("Januari 2026", "Title")]
    assert cell == "1. Pertanian valid"


# --------------------------------------------------------------------------- #
# HTML rendering
# --------------------------------------------------------------------------- #


def test_aggregation_to_html_emits_pre_wrap_css_for_newline_preservation() -> None:
    grouping = _grouping("Sektor", [_rule("Agri", ["pertanian"])])
    items = [
        NewsItem(
            title="A: pertanian",
            link="https://a.example.com/x",
            date_raw="",
            date_parsed=datetime(2026, 1, 5),
            source="PortalA",
            page=1,
        ),
        NewsItem(
            title="B: pertanian",
            link="https://b.example.com/x",
            date_raw="",
            date_parsed=datetime(2026, 1, 6),
            source="PortalA",
            page=1,
        ),
    ]
    frame = categorize_items_to_frame(items, grouping)
    agg = build_aggregation(frame, grouping)

    html = aggregation_to_html(agg)

    # The CSS rule that makes `\n` render as visible line breaks.
    assert "white-space: pre-wrap" in html
    # The wrapper class the dashboard scopes its CSS under.
    assert 'class="aggregation-wrapper"' in html
    # The actual numbered-list content survives the HTML conversion.
    assert "1. A: pertanian" in html
    assert "2. B: pertanian" in html


def test_aggregation_to_html_returns_empty_string_for_empty_frame() -> None:
    grouping = _grouping("Sektor", [_rule("Agri", ["pertanian"])])
    empty = categorize_items_to_frame([], grouping)
    agg = build_aggregation(empty, grouping)

    assert aggregation_to_html(agg) == ""


# --------------------------------------------------------------------------- #
# Quarterly aggregation (Iter 14)
# --------------------------------------------------------------------------- #


def test_quarter_of_month_maps_calendar_months_correctly() -> None:
    # Jan/Feb/Mar → 1
    assert quarter_of_month(1) == 1
    assert quarter_of_month(2) == 1
    assert quarter_of_month(3) == 1
    # Apr/May/Jun → 2
    assert quarter_of_month(4) == 2
    assert quarter_of_month(5) == 2
    assert quarter_of_month(6) == 2
    # Jul/Aug/Sep → 3
    assert quarter_of_month(7) == 3
    assert quarter_of_month(8) == 3
    assert quarter_of_month(9) == 3
    # Oct/Nov/Dec → 4
    assert quarter_of_month(10) == 4
    assert quarter_of_month(11) == 4
    assert quarter_of_month(12) == 4


def test_quarter_label_format_matches_spec_example() -> None:
    # User spec example: "Q1-2026", "Q2-2026"
    assert quarter_label(datetime(2026, 1, 15)) == "Q1-2026"
    assert quarter_label(datetime(2026, 4, 1)) == "Q2-2026"
    assert quarter_label(datetime(2026, 7, 31)) == "Q3-2026"
    assert quarter_label(datetime(2026, 12, 1)) == "Q4-2026"
    # Month-boundary cases.
    assert quarter_label(datetime(2026, 3, 31)) == "Q1-2026"
    assert quarter_label(datetime(2026, 10, 1)) == "Q4-2026"


def test_quarter_of_month_rejects_out_of_range_values() -> None:
    import pytest

    with pytest.raises(ValueError):
        quarter_of_month(0)
    with pytest.raises(ValueError):
        quarter_of_month(13)


def test_build_aggregation_quarter_top_level_is_quarter_not_month() -> None:
    grouping = _grouping("Sektor", [_rule("Agri", ["pertanian"])])
    items = [_item("Pertanian Jan", date_parsed=datetime(2026, 1, 5))]
    frame = categorize_items_to_frame(items, grouping)

    agg = build_aggregation(frame, grouping, period="quarter")

    assert agg.columns.nlevels == 2
    assert agg.columns.names == list(QUARTER_COLUMN_LEVEL_NAMES)
    quarters = agg.columns.get_level_values("Quarter").unique().tolist()
    assert quarters == ["Q1-2026"]
    fields = agg.columns.get_level_values("Field").tolist()
    assert fields == SUBCOLUMNS


def test_build_aggregation_quarter_collapses_months_in_same_quarter() -> None:
    """Jan + Feb + Mar articles all fold into the single Q1-2026 bucket."""
    grouping = _grouping("Sektor", [_rule("Agri", ["pertanian"])])
    items = [
        _item("Pertanian Jan", date_parsed=datetime(2026, 1, 5)),
        _item("Pertanian Feb", date_parsed=datetime(2026, 2, 10)),
        _item("Pertanian Mar", date_parsed=datetime(2026, 3, 20)),
    ]
    frame = categorize_items_to_frame(items, grouping)

    agg = build_aggregation(frame, grouping, period="quarter")

    quarters = agg.columns.get_level_values("Quarter").unique().tolist()
    assert quarters == ["Q1-2026"]
    title_cell = agg.loc["Agri", ("Q1-2026", "Title")]
    # All three titles should appear as a single numbered list.
    assert "1. Pertanian Jan" in title_cell
    assert "2. Pertanian Feb" in title_cell
    assert "3. Pertanian Mar" in title_cell


def test_build_aggregation_quarter_order_is_chronological_across_quarters() -> None:
    grouping = _grouping("Sektor", [_rule("Agri", ["pertanian"])])
    items = [
        _item("Pertanian Q3", date_parsed=datetime(2026, 8, 1)),
        _item("Pertanian Q1", date_parsed=datetime(2026, 2, 1)),
        _item("Pertanian Q4", date_parsed=datetime(2026, 11, 1)),
        _item("Pertanian Q2", date_parsed=datetime(2026, 5, 1)),
    ]
    frame = categorize_items_to_frame(items, grouping)

    agg = build_aggregation(frame, grouping, period="quarter")

    quarters = agg.columns.get_level_values("Quarter").unique().tolist()
    assert quarters == ["Q1-2026", "Q2-2026", "Q3-2026", "Q4-2026"]


def test_build_aggregation_quarter_year_boundary_orders_chronologically() -> None:
    grouping = _grouping("Sektor", [_rule("Agri", ["pertanian"])])
    items = [
        _item("Pertanian Q1 2026", date_parsed=datetime(2026, 2, 1)),
        _item("Pertanian Q4 2025", date_parsed=datetime(2025, 11, 1)),
    ]
    frame = categorize_items_to_frame(items, grouping)

    agg = build_aggregation(frame, grouping, period="quarter")

    quarters = agg.columns.get_level_values("Quarter").unique().tolist()
    assert quarters == ["Q4-2025", "Q1-2026"]


def test_build_aggregation_quarter_preserves_category_completeness() -> None:
    grouping = _grouping(
        "Sektor",
        [
            _rule("Energi", ["bbm"]),
            _rule("Agri", ["pertanian"]),
            _rule("Tambang", ["tambang"]),
        ],
    )
    items = [
        _item("Harga BBM naik", date_parsed=datetime(2026, 2, 1)),
        _item("Produksi pertanian stabil", date_parsed=datetime(2026, 3, 1)),
    ]
    frame = categorize_items_to_frame(items, grouping)

    agg = build_aggregation(frame, grouping, period="quarter")

    # All three categories present, sorted ascending; Tambang has no data
    # but still appears with empty cells.
    assert list(agg.index) == ["Agri", "Energi", "Tambang"]
    assert all(agg.loc["Tambang", col] == "" for col in agg.columns)


def test_build_aggregation_quarter_cells_are_numbered_lists() -> None:
    grouping = _grouping("Sektor", [_rule("Agri", ["pertanian"])])
    items = [
        NewsItem(
            title="First: pertanian",
            link="https://link1.com",
            date_raw="",
            date_parsed=datetime(2026, 1, 5),
            source="PortalA",
            page=1,
        ),
        NewsItem(
            title="Second: pertanian",
            link="https://link2.com",
            date_raw="",
            date_parsed=datetime(2026, 2, 10),
            source="PortalA",
            page=1,
        ),
    ]
    frame = categorize_items_to_frame(items, grouping)

    agg = build_aggregation(frame, grouping, period="quarter")

    title_cell = agg.loc["Agri", ("Q1-2026", "Title")]
    link_cell = agg.loc["Agri", ("Q1-2026", "Link")]
    date_cell = agg.loc["Agri", ("Q1-2026", "Date")]
    assert title_cell == "1. First: pertanian\n2. Second: pertanian"
    assert link_cell == "1. https://link1.com\n2. https://link2.com"
    assert date_cell == "1. 05-01-2026\n2. 10-02-2026"


def test_build_aggregation_default_period_is_month() -> None:
    """Callers that don't pass ``period=`` keep the Iter 13 monthly behaviour."""
    grouping = _grouping("Sektor", [_rule("Agri", ["pertanian"])])
    items = [_item("Pertanian", date_parsed=datetime(2026, 1, 5))]
    frame = categorize_items_to_frame(items, grouping)

    agg = build_aggregation(frame, grouping)  # no period kwarg

    assert agg.columns.names == list(COLUMN_LEVEL_NAMES)
    assert "Januari 2026" in agg.columns.get_level_values("Month").tolist()


def test_build_aggregation_rejects_unknown_period() -> None:
    import pytest

    grouping = _grouping("Sektor", [_rule("Agri", ["pertanian"])])
    frame = categorize_items_to_frame([], grouping)

    with pytest.raises(ValueError):
        build_aggregation(frame, grouping, period="weekly")  # type: ignore[arg-type]


def test_build_all_aggregations_threads_period_kwarg() -> None:
    g1 = _grouping("Sektor", [_rule("Agri", ["pertanian"])])
    g2 = _grouping("Pengeluaran", [_rule("Konsumsi", ["konsumsi"])])
    items = [
        _item("Pertanian Q1", date_parsed=datetime(2026, 2, 1)),
        _item("Konsumsi Q2", date_parsed=datetime(2026, 5, 1)),
    ]
    frames = {
        "Sektor": categorize_items_to_frame(items, g1),
        "Pengeluaran": categorize_items_to_frame(items, g2),
    }

    monthly = build_all_aggregations(frames, [g1, g2], period="month")
    quarterly = build_all_aggregations(frames, [g1, g2], period="quarter")

    assert "Februari 2026" in monthly["Sektor"].columns.get_level_values("Month").tolist()
    assert "Q1-2026" in quarterly["Sektor"].columns.get_level_values("Quarter").tolist()
    assert "Q2-2026" in quarterly["Pengeluaran"].columns.get_level_values("Quarter").tolist()


def test_empty_frame_quarter_mode_keeps_all_categories_no_columns() -> None:
    grouping = _grouping(
        "Sektor",
        [_rule("Agri", ["pertanian"]), _rule("Energi", ["bbm"])],
    )
    empty = categorize_items_to_frame([], grouping)

    agg = build_aggregation(empty, grouping, period="quarter")

    assert list(agg.index) == ["Agri", "Energi"]
    assert len(agg.columns) == 0
    assert agg.columns.names == list(QUARTER_COLUMN_LEVEL_NAMES)
