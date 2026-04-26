"""Tests for :mod:`ui.components.export_panel`.

Headless coverage of the workbook + CSV builders. The Streamlit
``render`` wrapper isn't tested here because download buttons require an
``AppTest`` harness; the building blocks are pure-Python so we drive
them directly.
"""

from __future__ import annotations

import io
from datetime import date

import pandas as pd
import pytest
from openpyxl import load_workbook

from config import (
    AppSettings,
    CategorizerGrouping,
    CategoryRule,
)
from scraper.models import NewsItem
from ui.components.export_panel import (
    _safe_sheet_name,
    build_workbook_bytes,
    raw_csv_bytes,
)


@pytest.fixture
def items() -> list[NewsItem]:
    return [
        NewsItem(
            title="Harga BBM dan pertanian naik",
            link="https://x.test/a1",
            date_raw="15 Jan 2026",
            date_parsed=date(2026, 1, 15),
            source="PortalA",
            page=1,
        ),
        NewsItem(
            title="Konsumsi rumah tangga naik",
            link="https://x.test/a2",
            date_raw="14 Jan 2026",
            date_parsed=date(2026, 1, 14),
            source="PortalA",
            page=1,
        ),
        NewsItem(
            title="Produksi pertanian stabil",
            link="https://x.test/a3",
            date_raw="13 Jan 2026",
            date_parsed=date(2026, 1, 13),
            source="PortalB",
            page=1,
        ),
    ]


@pytest.fixture
def groupings() -> list[CategorizerGrouping]:
    return [
        CategorizerGrouping(
            name="Sektor",
            rules=[
                CategoryRule(category="Agri", include_tokens=["pertanian"]),
                CategoryRule(category="Energi", include_tokens=["bbm"]),
            ],
        ),
        CategorizerGrouping(
            name="Pengeluaran",
            rules=[CategoryRule(category="Consumer", include_tokens=["konsumsi"])],
        ),
    ]


@pytest.fixture
def app_settings() -> AppSettings:
    return AppSettings()


def test_workbook_has_one_sheet_per_grouping_pair_plus_raw(items, groupings, app_settings) -> None:
    """Workbook layout: 1 raw sheet + 2 sheets per grouping (items + pivot)."""
    blob = build_workbook_bytes(items, groupings, app_settings)
    wb = load_workbook(io.BytesIO(blob))
    expected = {
        "Raw Data",
        "Sektor_items",
        "Sektor_pivot",
        "Pengeluaran_items",
        "Pengeluaran_pivot",
    }
    assert set(wb.sheetnames) == expected


def test_raw_sheet_contains_every_scraped_item(items, groupings, app_settings) -> None:
    blob = build_workbook_bytes(items, groupings, app_settings)
    wb = load_workbook(io.BytesIO(blob))
    raw = wb["Raw Data"]
    # Header + 3 items.
    assert raw.max_row == 4
    titles_in_sheet = {raw.cell(row=r, column=3).value for r in range(2, raw.max_row + 1)}
    assert titles_in_sheet == {it.title for it in items}


def test_grouping_items_sheet_explodes_multi_category_matches(
    items, groupings, app_settings
) -> None:
    """Article matching 2 rules in one grouping → 2 rows in the items sheet."""
    blob = build_workbook_bytes(items, groupings, app_settings)
    wb = load_workbook(io.BytesIO(blob))
    sektor = wb["Sektor_items"]
    # "Harga BBM dan pertanian" matches Agri AND Energi → 2 rows.
    # "Produksi pertanian" matches Agri only → 1 row.
    # Header + 3 rows total.
    assert sektor.max_row == 4
    categories = {sektor.cell(row=r, column=1).value for r in range(2, sektor.max_row + 1)}
    assert categories == {"Agri", "Energi"}


def test_pivot_sheet_includes_full_category_list_with_zero_counts(
    items, groupings, app_settings
) -> None:
    """Adding a rule that matches nothing must still produce a 0 column."""
    extended_grouping = CategorizerGrouping(
        name="Sektor",
        rules=[
            CategoryRule(category="Agri", include_tokens=["pertanian"]),
            CategoryRule(category="Energi", include_tokens=["bbm"]),
            CategoryRule(category="Tambang", include_tokens=["mineral"]),
        ],
    )
    blob = build_workbook_bytes(items, [extended_grouping], app_settings)
    wb = load_workbook(io.BytesIO(blob))
    pivot = wb["Sektor_pivot"]
    # Header row contains: index column + Agri + Energi + Tambang + Total.
    header = [pivot.cell(row=1, column=c).value for c in range(1, pivot.max_column + 1)]
    assert "Tambang" in header


def test_global_exclude_tokens_drop_items_from_grouping_sheets_only(items, groupings) -> None:
    """Global-exclude leaves the Raw sheet untouched but drops items from
    the grouping sheets — proves the export honours the same contract as
    the in-app frames."""
    settings = AppSettings(overall_exclude_tokens=["pertanian"])
    blob = build_workbook_bytes(items, groupings, settings)
    wb = load_workbook(io.BytesIO(blob))
    # Raw still has all 3.
    assert wb["Raw Data"].max_row == 4
    # Sektor_items: only the Konsumsi article would have matched Agri/Energi
    # but Konsumsi doesn't match either rule → 0 data rows.
    # Both Pertanian-mentioning articles are globally excluded → 0 data rows.
    assert wb["Sektor_items"].max_row == 1  # header only
    # Pengeluaran_items: Konsumsi article matches Consumer rule → 1 data row.
    assert wb["Pengeluaran_items"].max_row == 2


def test_grouping_frames_override_takes_precedence_over_recompute(
    items, groupings, app_settings
) -> None:
    """When the caller supplies ``grouping_frames``, the workbook should use
    that frame instead of re-running the auto-categorizer. This is how
    edited tables flow through the export."""
    edited = pd.DataFrame(
        [
            {
                "Category": "EditedCat",
                "Date": "01-01-2026",
                "Source": "PortalA",
                "Title": "Edited row",
                "Link": "https://x/edited",
                "Page": 1,
            }
        ]
    )
    blob = build_workbook_bytes(
        items,
        groupings,
        app_settings,
        grouping_frames={"Sektor": edited},
    )
    wb = load_workbook(io.BytesIO(blob))
    sektor = wb["Sektor_items"]
    # Header + 1 edited row.
    assert sektor.max_row == 2
    assert sektor.cell(row=2, column=1).value == "EditedCat"


def test_raw_csv_bytes_roundtrips_through_pandas(items) -> None:
    blob = raw_csv_bytes(items)
    df = pd.read_csv(io.BytesIO(blob))
    assert list(df.columns) == ["Date", "Source", "Title", "Link", "Page"]
    assert set(df["Title"]) == {it.title for it in items}


def test_sheet_name_clamps_to_31_chars_and_dedupes() -> None:
    used: set[str] = set()
    long_name = "x" * 50
    first = _safe_sheet_name(long_name, used)
    assert len(first) == 31
    second = _safe_sheet_name(long_name, used)
    # Distinct from the first, still ≤31, has a numeric suffix.
    assert second != first
    assert len(second) <= 31
    assert second.endswith("_2")


def test_sheet_name_strips_invalid_chars() -> None:
    used: set[str] = set()
    name = _safe_sheet_name("foo/bar:baz?", used)
    assert "/" not in name
    assert ":" not in name
    assert "?" not in name


def test_empty_items_still_produces_valid_workbook(groupings, app_settings) -> None:
    """An empty run should still produce a structured workbook (just no data rows)."""
    blob = build_workbook_bytes([], groupings, app_settings)
    wb = load_workbook(io.BytesIO(blob))
    # Raw Data + items + pivot per grouping.
    assert "Raw Data" in wb.sheetnames
    assert "Sektor_items" in wb.sheetnames
    # Header row exists; no data rows.
    assert wb["Raw Data"].max_row == 1
