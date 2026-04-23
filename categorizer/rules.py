"""CSV/Excel import/export for categorization rules.

Used by the Settings page to upload a rule table and by future exporters.

Expected columns (case-insensitive; extras ignored):
    Category, Include_tokens, Exclude_tokens

Tokens may be separated by commas or semicolons. Whitespace is trimmed.
"""

from __future__ import annotations

import io
from typing import IO

import pandas as pd

from config import CategoryRule

_TOKEN_SEP = (",", ";")


def _split_tokens(raw: object) -> list[str]:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return []
    text = str(raw).strip()
    if not text:
        return []
    for sep in _TOKEN_SEP[1:]:
        text = text.replace(sep, _TOKEN_SEP[0])
    return [t.strip() for t in text.split(_TOKEN_SEP[0]) if t.strip()]


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    mapping = {col: col.strip().lower() for col in df.columns}
    df = df.rename(columns=mapping)
    return df


def rules_from_dataframe(df: pd.DataFrame) -> list[CategoryRule]:
    """Parse a DataFrame with at minimum a ``category`` column into rules."""
    df = _normalize_columns(df.copy())
    if "category" not in df.columns:
        raise ValueError("Missing required column: 'Category'")

    rules: list[CategoryRule] = []
    for _, row in df.iterrows():
        category = str(row.get("category", "")).strip()
        if not category:
            continue
        rules.append(
            CategoryRule(
                category=category,
                include_tokens=_split_tokens(row.get("include_tokens", "")),
                exclude_tokens=_split_tokens(row.get("exclude_tokens", "")),
            )
        )
    return rules


def rules_from_csv(buf: IO[bytes] | bytes) -> list[CategoryRule]:
    if isinstance(buf, (bytes, bytearray)):
        buf = io.BytesIO(buf)
    df = pd.read_csv(buf)
    return rules_from_dataframe(df)


def rules_from_excel(buf: IO[bytes] | bytes) -> list[CategoryRule]:
    if isinstance(buf, (bytes, bytearray)):
        buf = io.BytesIO(buf)
    df = pd.read_excel(buf)
    return rules_from_dataframe(df)


def rules_to_dataframe(rules: list[CategoryRule]) -> pd.DataFrame:
    # Explicit string dtype so st.data_editor TextColumn works even when
    # rules is empty (pandas would otherwise default empty columns to
    # float64 and st.column_config.TextColumn rejects FLOAT-typed columns).
    return pd.DataFrame(
        {
            "Category": pd.Series([r.category for r in rules], dtype="string"),
            "Include_tokens": pd.Series(
                [", ".join(r.include_tokens) for r in rules], dtype="string"
            ),
            "Exclude_tokens": pd.Series(
                [", ".join(r.exclude_tokens) for r in rules], dtype="string"
            ),
        }
    )


def rules_from_editor_dataframe(df: pd.DataFrame) -> list[CategoryRule]:
    """Variant of ``rules_from_dataframe`` tolerant of the ``st.data_editor`` output.

    ``st.data_editor`` preserves the original column names (e.g. 'Category',
    'Include_tokens'), so we just delegate.
    """
    return rules_from_dataframe(df)


__all__ = [
    "rules_from_csv",
    "rules_from_dataframe",
    "rules_from_editor_dataframe",
    "rules_from_excel",
    "rules_to_dataframe",
]
