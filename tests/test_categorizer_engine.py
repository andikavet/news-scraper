"""Unit tests for the Iter 5 categorization engine."""

from __future__ import annotations

from datetime import date

import pandas as pd

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
from config import CategorizerGrouping, CategoryRule
from scraper.models import NewsItem

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _item(
    title: str, source: str = "PortalA", page: int = 1, d: date | None = date(2026, 4, 1)
) -> NewsItem:
    return NewsItem(
        title=title,
        link=f"https://example.com/{title.replace(' ', '-').lower()}",
        date_raw="5 menit lalu",
        date_parsed=d,
        source=source,
        page=page,
    )


def _rule(
    category: str, include: list[str] | None = None, exclude: list[str] | None = None
) -> CategoryRule:
    return CategoryRule(
        category=category,
        include_tokens=include or [],
        exclude_tokens=exclude or [],
    )


def _grouping(name: str, rules: list[CategoryRule]) -> CategorizerGrouping:
    return CategorizerGrouping(name=name, rules=rules)


# --------------------------------------------------------------------------- #
# normalize()
# --------------------------------------------------------------------------- #


def test_normalize_lowercases_and_strips_punctuation() -> None:
    assert normalize("Harga BBM NAIK!") == "harga bbm naik"


def test_normalize_handles_indonesian_accents_and_unicode() -> None:
    # "é" decomposes to e + combining accent; latin non-ascii collapsed.
    assert normalize("Café Négara — Kenaikan") == "cafe negara kenaikan"


def test_normalize_collapses_multiple_punctuation_into_single_space() -> None:
    assert normalize("foo,,bar...baz") == "foo bar baz"


def test_normalize_empty_input_returns_empty_string() -> None:
    assert normalize("") == ""


# --------------------------------------------------------------------------- #
# rule_matches()
# --------------------------------------------------------------------------- #


def test_rule_with_no_include_tokens_never_matches() -> None:
    r = _rule("Agri", include=[], exclude=[])
    assert rule_matches(normalize("pertanian naik"), r) is False


def test_rule_matches_on_any_include_token_not_all() -> None:
    r = _rule("Agri", include=["padi", "jagung", "sawit"])
    # Only one include token present; still matches because semantics are OR.
    assert rule_matches(normalize("produksi jagung nasional naik"), r) is True


def test_rule_is_rejected_when_any_exclude_token_matches() -> None:
    r = _rule("Agri", include=["pertanian"], exclude=["ekspor"])
    assert rule_matches(normalize("ekspor pertanian naik"), r) is False


def test_rule_token_matching_respects_word_boundaries() -> None:
    r = _rule("Agri", include=["agri"])
    # "agriculture" is a different word — should NOT match "agri".
    assert rule_matches(normalize("agriculture modern"), r) is False
    # But "sektor agri" should match.
    assert rule_matches(normalize("sektor agri tumbuh"), r) is True


def test_rule_multiword_token_requires_consecutive_words() -> None:
    r = _rule("Energi", include=["harga minyak"])
    assert rule_matches(normalize("harga minyak dunia naik"), r) is True
    # Words present but not consecutive — must not match.
    assert rule_matches(normalize("harga cabai dan minyak goreng turun"), r) is False


def test_rule_tokens_are_normalized_same_way_as_title() -> None:
    # Config might store the token with mixed case + punctuation.
    r = _rule("Agri", include=["BBM."])
    assert rule_matches(normalize("harga bbm naik"), r) is True


# --------------------------------------------------------------------------- #
# matches_for_title() — multi-category
# --------------------------------------------------------------------------- #


def test_matches_for_title_returns_every_matching_category_in_rule_order() -> None:
    g = _grouping(
        "GDP Sector",
        [
            _rule("Agri", include=["pertanian", "padi"]),
            _rule("Energi", include=["bbm", "minyak"]),
            _rule("Jasa", include=["wisata", "pariwisata"]),
        ],
    )
    # Title triggers Agri + Energi, not Jasa.
    assert matches_for_title("Harga BBM dan hasil pertanian naik", g) == ["Agri", "Energi"]


def test_matches_for_title_empty_when_nothing_matches() -> None:
    g = _grouping("X", [_rule("Agri", include=["pertanian"])])
    assert matches_for_title("berita politik terbaru", g) == []


# --------------------------------------------------------------------------- #
# is_globally_excluded()
# --------------------------------------------------------------------------- #


def test_is_globally_excluded_matches_any_token() -> None:
    assert is_globally_excluded("Advertorial: buy now", ["advertorial", "iklan"]) is True
    assert is_globally_excluded("Berita ekonomi", ["advertorial"]) is False


def test_is_globally_excluded_empty_list_is_noop() -> None:
    assert is_globally_excluded("anything here", []) is False


# --------------------------------------------------------------------------- #
# items_to_raw_dataframe()
# --------------------------------------------------------------------------- #


def test_items_to_raw_dataframe_empty_returns_frame_with_string_columns() -> None:
    df = items_to_raw_dataframe([])
    assert list(df.columns) == RAW_COLUMNS
    assert len(df) == 0
    # Critical: must not be float64, else st.data_editor blows up.
    for col in ("Date", "Source", "Title", "Link"):
        assert str(df[col].dtype) == "string"


def test_items_to_raw_dataframe_formats_dates_and_preserves_order() -> None:
    items = [
        _item("A news", d=date(2026, 4, 1)),
        _item("B news", d=date(2026, 3, 15)),
        _item("Undated", d=None),
    ]
    df = items_to_raw_dataframe(items)
    assert list(df["Title"]) == ["A news", "B news", "Undated"]
    assert list(df["Date"]) == ["01-04-2026", "15-03-2026", "5 menit lalu"]


def test_items_to_raw_dataframe_does_not_apply_global_excludes() -> None:
    # Raw table is for auditing — global excludes are applied only inside
    # the grouping frames. This test pins down that contract.
    items = [_item("Advertorial: produk promo"), _item("Berita ekonomi")]
    df = items_to_raw_dataframe(items)
    assert len(df) == 2


# --------------------------------------------------------------------------- #
# categorize_items_to_frame() — the heart of Iter 5
# --------------------------------------------------------------------------- #


def test_explode_produces_one_row_per_matched_category() -> None:
    """Single item matching 2 categories → 2 rows in the grouping frame."""
    g = _grouping(
        "GDP Sector",
        [
            _rule("Agri", include=["pertanian"]),
            _rule("Energi", include=["bbm"]),
        ],
    )
    items = [_item("Harga BBM dan pertanian naik")]
    df = categorize_items_to_frame(items, g)
    assert len(df) == 2
    assert sorted(df["Category"].tolist()) == ["Agri", "Energi"]
    # Same article, so source/title/link match on both rows.
    assert df["Title"].nunique() == 1
    assert df["Link"].nunique() == 1


def test_items_matching_no_rule_are_omitted_from_grouping_frame() -> None:
    g = _grouping("X", [_rule("Agri", include=["pertanian"])])
    items = [_item("berita politik"), _item("harga pertanian naik")]
    df = categorize_items_to_frame(items, g)
    assert len(df) == 1
    assert df.iloc[0]["Title"] == "harga pertanian naik"


def test_global_excludes_drop_item_before_categorization() -> None:
    g = _grouping("X", [_rule("Agri", include=["pertanian"])])
    items = [
        _item("Advertorial: harga pertanian naik"),  # would match Agri but is ad
        _item("harga pertanian stabil"),  # should appear
    ]
    df = categorize_items_to_frame(items, g, global_excludes=["advertorial"])
    assert len(df) == 1
    assert "Advertorial" not in df.iloc[0]["Title"]


def test_empty_items_produces_frame_with_correct_columns_and_dtypes() -> None:
    g = _grouping("X", [_rule("Agri", include=["pertanian"])])
    df = categorize_items_to_frame([], g)
    assert list(df.columns) == GROUPING_COLUMNS
    assert len(df) == 0
    for col in ("Category", "Date", "Source", "Title", "Link"):
        assert str(df[col].dtype) == "string"


def test_empty_grouping_produces_empty_frame_never_crashes() -> None:
    g = _grouping("X", [])
    items = [_item("anything")]
    df = categorize_items_to_frame(items, g)
    assert len(df) == 0
    assert list(df.columns) == GROUPING_COLUMNS


def test_categorize_all_groupings_returns_frame_per_grouping() -> None:
    g1 = _grouping("Sector", [_rule("Agri", include=["pertanian"])])
    g2 = _grouping("Expenditure", [_rule("Consumer", include=["konsumsi"])])
    items = [
        _item("harga pertanian naik"),
        _item("konsumsi rumah tangga turun"),
        _item("berita politik"),
    ]
    frames = categorize_all_groupings(items, [g1, g2])
    assert set(frames.keys()) == {"Sector", "Expenditure"}
    assert len(frames["Sector"]) == 1
    assert len(frames["Expenditure"]) == 1


def test_row_order_within_grouping_follows_input_then_rule_order() -> None:
    """Deterministic output is required for the Iter 6 pivot logic."""
    g = _grouping(
        "X",
        [
            _rule("First", include=["alpha"]),
            _rule("Second", include=["beta"]),
        ],
    )
    items = [
        _item("alpha and beta together"),  # matches First then Second
        _item("only beta"),  # matches Second only
    ]
    df = categorize_items_to_frame(items, g)
    assert df["Category"].tolist() == ["First", "Second", "Second"]
    assert df["Title"].tolist()[0] == "alpha and beta together"
    assert df["Title"].tolist()[-1] == "only beta"


def test_undated_items_pass_through_with_raw_date_string() -> None:
    g = _grouping("X", [_rule("Agri", include=["pertanian"])])
    items = [_item("pertanian naik", d=None)]
    df = categorize_items_to_frame(items, g)
    assert len(df) == 1
    assert df.iloc[0]["Date"] == "5 menit lalu"


# --------------------------------------------------------------------------- #
# Sanity: no Streamlit / I/O imports sneaked in
# --------------------------------------------------------------------------- #


def test_engine_module_has_no_streamlit_dependency() -> None:
    import importlib
    import sys

    # Force re-import in isolation so we can inspect the module graph.
    for mod_name in list(sys.modules):
        if mod_name.startswith("categorizer.engine"):
            del sys.modules[mod_name]
    mod = importlib.import_module("categorizer.engine")
    # Walk direct module imports (best-effort check).
    with open(mod.__file__) as f:  # type: ignore[arg-type]
        source = f.read()
    assert "import streamlit" not in source
    assert "from streamlit" not in source


# --------------------------------------------------------------------------- #
# Smoke: pd.DataFrame round-trip still has expected columns + dtypes
# --------------------------------------------------------------------------- #


def test_frames_serialize_cleanly_to_csv_and_back() -> None:
    """Regression guard: raw frame should round-trip through pandas CSV."""
    items = [_item("harga bbm naik"), _item("pertanian stabil")]
    df = items_to_raw_dataframe(items)
    csv_text = df.to_csv(index=False)
    restored = pd.read_csv(pd.io.common.StringIO(csv_text))
    assert list(restored.columns) == RAW_COLUMNS
    assert len(restored) == 2
