"""Tests for ``categorizer.rules`` CSV/Excel import + round-trip."""

from __future__ import annotations

import io

import pandas as pd
import pytest

from categorizer.rules import (
    rules_from_csv,
    rules_from_dataframe,
    rules_from_excel,
    rules_to_dataframe,
)


def test_rules_from_dataframe_basic():
    df = pd.DataFrame(
        {
            "Category": ["Agriculture", "Mining", ""],  # empty row skipped
            "Include_tokens": ["padi, sawah", "tambang;batu bara", "junk"],
            "Exclude_tokens": ["", " subsidi , impor ", ""],
        }
    )
    rules = rules_from_dataframe(df)
    assert [r.category for r in rules] == ["Agriculture", "Mining"]
    assert rules[0].include_tokens == ["padi", "sawah"]
    assert rules[1].include_tokens == ["tambang", "batu bara"]
    assert rules[1].exclude_tokens == ["subsidi", "impor"]


def test_rules_from_dataframe_missing_category_column_raises():
    df = pd.DataFrame({"name": ["x"], "tokens": ["y"]})
    with pytest.raises(ValueError, match="Category"):
        rules_from_dataframe(df)


def test_rules_from_csv_round_trip():
    csv = "Category,Include_tokens,Exclude_tokens\nEnergy,listrik; migas,subsidi\n"
    rules = rules_from_csv(csv.encode("utf-8"))
    assert len(rules) == 1
    assert rules[0].category == "Energy"
    assert rules[0].include_tokens == ["listrik", "migas"]


def test_rules_to_dataframe_round_trip():
    df = pd.DataFrame(
        {
            "Category": ["A", "B"],
            "Include_tokens": ["x,y", "z"],
            "Exclude_tokens": ["", "w"],
        }
    )
    rules = rules_from_dataframe(df)
    out = rules_to_dataframe(rules)
    assert list(out.columns) == ["Category", "Include_tokens", "Exclude_tokens"]
    assert out.iloc[0]["Include_tokens"] == "x, y"
    assert out.iloc[1]["Exclude_tokens"] == "w"


def test_rules_from_excel_round_trip():
    src = pd.DataFrame(
        {
            "Category": ["Trade"],
            "Include_tokens": ["ekspor,impor"],
            "Exclude_tokens": [""],
        }
    )
    buf = io.BytesIO()
    src.to_excel(buf, index=False)
    buf.seek(0)
    rules = rules_from_excel(buf)
    assert rules[0].category == "Trade"
    assert rules[0].include_tokens == ["ekspor", "impor"]
