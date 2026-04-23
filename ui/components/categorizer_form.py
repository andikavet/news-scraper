"""Categorizer CRUD UI component for the Settings page.

Exposes grouping-level operations (add / rename / delete) and rule-level
editing via ``st.data_editor``. Supports CSV/Excel upload for bulk rule
creation and CSV export for round-tripping into spreadsheets.
"""

from __future__ import annotations

import streamlit as st

from categorizer.rules import (
    rules_from_csv,
    rules_from_editor_dataframe,
    rules_from_excel,
    rules_to_dataframe,
)
from config import (
    CategorizerGrouping,
    load_categorizers,
    save_categorizers,
)


def _add_grouping_form(groupings: list[CategorizerGrouping]) -> None:
    with st.form("add_grouping"):
        st.markdown("**Add grouping**")
        new_name = st.text_input("Grouping name (e.g. 'GDP Sector')", key="add_group_name")
        submit = st.form_submit_button("Add grouping")
    if submit:
        new_name = new_name.strip()
        if not new_name:
            st.error("Grouping name required.")
            return
        if any(g.name == new_name for g in groupings):
            st.error(f"Grouping '{new_name}' already exists.")
            return
        groupings = list(groupings) + [CategorizerGrouping(name=new_name, rules=[])]
        save_categorizers(groupings)
        st.success(f"Added grouping '{new_name}'.")
        st.rerun()


def _edit_grouping(grouping: CategorizerGrouping, all_groupings: list[CategorizerGrouping]) -> None:
    st.markdown(f"### {grouping.name}")

    upload = st.file_uploader(
        "Upload CSV or Excel to replace rules (columns: Category, Include_tokens, Exclude_tokens)",
        type=["csv", "xlsx", "xls"],
        key=f"upload_{grouping.name}",
    )
    if upload is not None:
        try:
            if upload.name.lower().endswith(".csv"):
                new_rules = rules_from_csv(upload.getvalue())
            else:
                new_rules = rules_from_excel(upload.getvalue())
        except Exception as e:  # noqa: BLE001  — surface parse errors to the UI
            st.error(f"Upload failed: {e}")
        else:
            updated = [
                g if g.name != grouping.name else CategorizerGrouping(name=g.name, rules=new_rules)
                for g in all_groupings
            ]
            save_categorizers(updated)
            st.success(f"Imported {len(new_rules)} rule(s) into '{grouping.name}'.")
            st.rerun()

    df = rules_to_dataframe(grouping.rules)
    edited = st.data_editor(
        df,
        num_rows="dynamic",
        use_container_width=True,
        key=f"rules_editor_{grouping.name}",
        column_config={
            "Category": st.column_config.TextColumn("Category", required=True),
            "Include_tokens": st.column_config.TextColumn(
                "Include_tokens",
                help="Comma-separated tokens. Article title must contain at least one.",
            ),
            "Exclude_tokens": st.column_config.TextColumn(
                "Exclude_tokens",
                help="Comma-separated tokens. Any match disqualifies the category.",
            ),
        },
    )

    c1, c2, c3 = st.columns([1, 1, 1])
    if c1.button("Save rules", key=f"save_{grouping.name}", type="primary"):
        try:
            new_rules = rules_from_editor_dataframe(edited)
        except Exception as e:  # noqa: BLE001
            st.error(f"Validation failed: {e}")
        else:
            updated = [
                g if g.name != grouping.name else CategorizerGrouping(name=g.name, rules=new_rules)
                for g in all_groupings
            ]
            save_categorizers(updated)
            st.success(f"Saved {len(new_rules)} rule(s) for '{grouping.name}'.")
            st.rerun()

    csv_bytes = df.to_csv(index=False).encode("utf-8")
    c2.download_button(
        "Export CSV",
        data=csv_bytes,
        file_name=f"{grouping.name}_rules.csv",
        mime="text/csv",
        key=f"export_{grouping.name}",
    )

    if c3.button(
        f"Delete grouping '{grouping.name}'",
        key=f"del_{grouping.name}",
        type="secondary",
    ):
        updated = [g for g in all_groupings if g.name != grouping.name]
        save_categorizers(updated)
        st.success(f"Deleted grouping '{grouping.name}'.")
        st.rerun()


def render() -> None:
    groupings = load_categorizers()
    _add_grouping_form(groupings)
    st.divider()
    if not groupings:
        st.info("No categorizer groupings yet. Add one above.")
        return
    for g in groupings:
        _edit_grouping(g, groupings)
        st.divider()


__all__ = ["render"]
