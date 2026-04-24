"""Unit tests for the Iter 6 pivot builder."""

from __future__ import annotations

import pandas as pd

from categorizer.engine import categorize_items_to_frame
from categorizer.pivot import (
    PIVOT_TOTAL_COL,
    PIVOT_TOTAL_ROW,
    build_all_pivots,
    build_pivot,
)
from config import CategorizerGrouping, CategoryRule
from scraper.models import NewsItem


def _rule(category: str, include: list[str]) -> CategoryRule:
    return CategoryRule(category=category, include_tokens=include)


def _grouping(name: str, rules: list[CategoryRule]) -> CategorizerGrouping:
    return CategorizerGrouping(name=name, rules=rules)


def _item(title: str, source: str = "PortalA", page: int = 1) -> NewsItem:
    return NewsItem(
        title=title,
        link=f"https://example.com/{title.replace(' ', '-').lower()}",
        date_raw="",
        date_parsed=None,
        source=source,
        page=page,
    )


# --------------------------------------------------------------------------- #
# Full-category reindex (the headline PRD requirement)
# --------------------------------------------------------------------------- #


def test_pivot_includes_every_configured_category_even_with_zero_matches() -> None:
    grouping = _grouping(
        "Sektor",
        [
            _rule("Agri", ["pertanian"]),
            _rule("Energi", ["bbm"]),
            _rule("Tambang", ["tambang"]),  # never matched below
        ],
    )
    items = [_item("Harga BBM naik"), _item("Produksi pertanian stabil")]
    frame = categorize_items_to_frame(items, grouping)

    pivot = build_pivot(frame, grouping)

    # Column order mirrors rule declaration order, plus a trailing Total col.
    assert list(pivot.columns) == ["Agri", "Energi", "Tambang", PIVOT_TOTAL_COL]
    # Tambang column exists as zeros even though nothing matched it.
    assert int(pivot.loc["PortalA", "Tambang"]) == 0
    # Non-zero matches are counted correctly.
    assert int(pivot.loc["PortalA", "Agri"]) == 1
    assert int(pivot.loc["PortalA", "Energi"]) == 1


# --------------------------------------------------------------------------- #
# Multi-source + multi-category totals
# --------------------------------------------------------------------------- #


def test_pivot_totals_row_and_column() -> None:
    grouping = _grouping("Sektor", [_rule("Agri", ["pertanian"]), _rule("Energi", ["bbm"])])
    items = [
        _item("Harga BBM dan pertanian naik", source="PortalA"),  # 2 matches A
        _item("Produksi pertanian stabil", source="PortalA"),  # Agri A
        _item("Harga BBM turun", source="PortalB"),  # Energi B
    ]
    frame = categorize_items_to_frame(items, grouping)

    pivot = build_pivot(frame, grouping)

    # Per-source row totals
    assert int(pivot.loc["PortalA", PIVOT_TOTAL_COL]) == 3
    assert int(pivot.loc["PortalB", PIVOT_TOTAL_COL]) == 1
    # Grand total row is the sum of per-source totals
    assert int(pivot.loc[PIVOT_TOTAL_ROW, PIVOT_TOTAL_COL]) == 4
    # Per-category column totals
    assert int(pivot.loc[PIVOT_TOTAL_ROW, "Agri"]) == 2
    assert int(pivot.loc[PIVOT_TOTAL_ROW, "Energi"]) == 2


def test_pivot_rows_are_sources_exploded_counted_once_per_category() -> None:
    """A 2-rule-matching article contributes once to each category — not twice."""
    grouping = _grouping("Sektor", [_rule("Agri", ["pertanian"]), _rule("Energi", ["bbm"])])
    items = [_item("Harga BBM dan pertanian naik", source="PortalA")]
    frame = categorize_items_to_frame(items, grouping)

    pivot = build_pivot(frame, grouping)

    assert int(pivot.loc["PortalA", "Agri"]) == 1
    assert int(pivot.loc["PortalA", "Energi"]) == 1


# --------------------------------------------------------------------------- #
# Edge cases
# --------------------------------------------------------------------------- #


def test_pivot_empty_frame_still_shows_every_category_as_zero_column() -> None:
    grouping = _grouping("Sektor", [_rule("Agri", ["pertanian"]), _rule("Energi", ["bbm"])])
    empty = categorize_items_to_frame([], grouping)

    pivot = build_pivot(empty, grouping)

    assert list(pivot.columns) == ["Agri", "Energi", PIVOT_TOTAL_COL]
    # No source rows, no Total row — the header of categories is the point.
    assert len(pivot) == 0


def test_pivot_grouping_with_no_rules_returns_empty_frame() -> None:
    grouping = _grouping("Empty", [])
    frame = pd.DataFrame(columns=["Category", "Date", "Source", "Title", "Link", "Page"])

    pivot = build_pivot(frame, grouping)

    assert pivot.empty
    assert list(pivot.columns) == []


def test_build_all_pivots_keyed_by_grouping_name() -> None:
    g1 = _grouping("Sektor", [_rule("Agri", ["pertanian"])])
    g2 = _grouping("Pengeluaran", [_rule("Konsumsi", ["konsumsi"])])
    items = [_item("Konsumsi rumah tangga naik"), _item("Produksi pertanian stabil")]
    frames = {
        "Sektor": categorize_items_to_frame(items, g1),
        "Pengeluaran": categorize_items_to_frame(items, g2),
    }

    pivots = build_all_pivots(frames, [g1, g2])

    assert set(pivots.keys()) == {"Sektor", "Pengeluaran"}
    assert int(pivots["Sektor"].loc["PortalA", "Agri"]) == 1
    assert int(pivots["Pengeluaran"].loc["PortalA", "Konsumsi"]) == 1


def test_pivot_unknown_source_from_edits_appears_as_its_own_row() -> None:
    """If the user edits rows via data_editor to change Source, the pivot reflects that.

    We simulate the result of an edit: the exploded frame has a Source the
    original scraper wouldn't have emitted. This is exactly the flow that
    'Update Pivot' triggers.
    """
    grouping = _grouping("Sektor", [_rule("Agri", ["pertanian"])])
    edited_frame = pd.DataFrame(
        [
            {
                "Category": "Agri",
                "Date": "01-04-2026",
                "Source": "ManuallyEntered",
                "Title": "Pertanian swasembada",
                "Link": "https://example.com/x",
                "Page": 1,
            }
        ]
    )

    pivot = build_pivot(edited_frame, grouping)

    assert "ManuallyEntered" in pivot.index
    assert int(pivot.loc["ManuallyEntered", "Agri"]) == 1
