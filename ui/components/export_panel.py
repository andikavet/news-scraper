"""Section D' — download buttons for the latest run's results.

Builds an Excel workbook containing every dataframe the user can see in
section D (Raw Data + each grouping's editable items + pivot) plus a
single-click CSV download for the Raw Data tab. The workbook is the
canonical export — it preserves multiple sheets — while CSV is the
lightweight fallback for users who just want the un-categorized raw
list in their preferred tool.

The pure-Python ``build_workbook_bytes`` and ``raw_csv_bytes`` helpers
are exported separately so they're unit-testable without spinning up
Streamlit. ``render`` is the Streamlit-aware wrapper that surfaces the
download buttons.

Design notes:

- Sheet names are clamped to Excel's 31-char limit and stripped of the
  characters Excel rejects (``[]:*?/\\``). Two groupings whose names
  collide after clamping get a numeric suffix to keep the sheets
  distinct.
- Pivots are built from the user's **edited** frame for each grouping
  (read from the ``results_tabs`` session-state cache) when available,
  falling back to the auto-categorized frame otherwise. This matches
  what's visible in the dashboard.
- Empty groupings (no rules / no matched rows) still get a sheet so the
  workbook structure is predictable.
"""

from __future__ import annotations

import io
import re
from datetime import datetime

import pandas as pd
import streamlit as st

from categorizer import build_aggregation, categorize_items_to_frame, items_to_raw_dataframe
from config import AppSettings, CategorizerGrouping
from scraper.models import NewsItem
from ui.components.results_tabs import K_EDITOR_FRAME_PREFIX

_INVALID_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")
_MAX_SHEET_NAME_LEN = 31


def _safe_sheet_name(raw: str, used: set[str]) -> str:
    """Clamp ``raw`` to a valid, unique Excel sheet name (≤31 chars)."""
    cleaned = _INVALID_SHEET_CHARS.sub("_", raw).strip() or "sheet"
    base = cleaned[:_MAX_SHEET_NAME_LEN]
    name = base
    suffix = 2
    while name in used:
        # Reserve room for a numeric suffix while staying under the 31-char cap.
        room = _MAX_SHEET_NAME_LEN - len(f"_{suffix}")
        name = f"{base[:room]}_{suffix}"
        suffix += 1
    used.add(name)
    return name


def _grouping_items_frame(
    grouping: CategorizerGrouping,
    items: list[NewsItem],
    app_settings: AppSettings,
) -> pd.DataFrame:
    """Return the user's edited frame if cached, else the auto-categorized one."""
    cached = st.session_state.get(K_EDITOR_FRAME_PREFIX + grouping.name)
    if isinstance(cached, pd.DataFrame):
        return cached
    return categorize_items_to_frame(
        items,
        grouping,
        global_excludes=app_settings.overall_exclude_tokens,
    )


def build_workbook_bytes(
    items: list[NewsItem],
    groupings: list[CategorizerGrouping],
    app_settings: AppSettings,
    *,
    grouping_frames: dict[str, pd.DataFrame] | None = None,
) -> bytes:
    """Build the multi-sheet Excel workbook for the current run.

    ``grouping_frames`` lets callers pass already-computed exploded frames
    (e.g. read from ``results_tabs`` session state) instead of having
    this function recompute them. When ``None``, the auto-categorized
    frame is computed for every grouping. Tests use the explicit form to
    stay headless.
    """
    raw_df = items_to_raw_dataframe(items)
    used: set[str] = set()
    raw_sheet = _safe_sheet_name("Raw Data", used)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        raw_df.to_excel(writer, sheet_name=raw_sheet, index=False)
        for grouping in groupings:
            if grouping_frames is not None and grouping.name in grouping_frames:
                items_df = grouping_frames[grouping.name]
            else:
                items_df = categorize_items_to_frame(
                    items,
                    grouping,
                    global_excludes=app_settings.overall_exclude_tokens,
                )
            agg_df = build_aggregation(items_df, grouping)

            items_sheet = _safe_sheet_name(f"{grouping.name}_items", used)
            agg_sheet = _safe_sheet_name(f"{grouping.name}_aggregation", used)
            items_df.to_excel(writer, sheet_name=items_sheet, index=False)
            # When there are no dated rows, the aggregation frame has an
            # empty MultiIndex column header, which pandas refuses to write
            # to Excel (zip strict=True barfs). Fall back to writing just
            # the category index column so the sheet still exists with the
            # full row list — keeps the workbook structure predictable.
            if len(agg_df.columns) == 0:
                pd.DataFrame(index=agg_df.index).to_excel(writer, sheet_name=agg_sheet, index=True)
            else:
                # Aggregation keeps its Category index + 2-level MultiIndex
                # column header. Excel renders both natively; the
                # numbered-list `\n` separators turn into multi-line cells
                # with wrap-text.
                agg_df.to_excel(writer, sheet_name=agg_sheet, index=True)
    return buf.getvalue()


def raw_csv_bytes(items: list[NewsItem]) -> bytes:
    """Return UTF-8 CSV bytes of the Raw Data frame (BOM-prefixed for Excel)."""
    df = items_to_raw_dataframe(items)
    return df.to_csv(index=False).encode("utf-8-sig")


def _timestamp_suffix() -> str:
    """``YYYYMMDD-HHMMSS`` for filenames — readable + sortable."""
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def render(
    items: list[NewsItem],
    groupings: list[CategorizerGrouping],
    app_settings: AppSettings,
) -> None:
    """Streamlit entrypoint — surfaces download buttons.

    Both downloads are built eagerly on every dashboard render. ``data=``
    callables would let us defer construction until click, but Streamlit
    rotates the deferred-file token on each rerun and rejects the click
    with "Deferred file not found" when the user clicks one button
    immediately after another. Pre-computing the bytes side-steps that
    by handing Streamlit a stable buffer it can serve directly. Both
    payloads are small (a workbook with a 4-item run is <10 KB), so the
    eager build cost is dominated by the surrounding dashboard render.
    """
    if not items:
        return

    cols = st.columns([1, 1, 4])
    suffix = _timestamp_suffix()
    xlsx_payload = build_workbook_bytes(items, groupings, app_settings)
    csv_payload = raw_csv_bytes(items)
    with cols[0]:
        st.download_button(
            "Download .xlsx",
            data=xlsx_payload,
            file_name=f"news-scrape-{suffix}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="export_xlsx",
            use_container_width=True,
        )
    with cols[1]:
        st.download_button(
            "Download Raw .csv",
            data=csv_payload,
            file_name=f"news-scrape-raw-{suffix}.csv",
            mime="text/csv",
            key="export_raw_csv",
            use_container_width=True,
        )
    with cols[2]:
        st.caption(
            f"Workbook contains 1 raw sheet + 2 sheets per grouping "
            f"({len(groupings)} grouping{'s' if len(groupings) != 1 else ''})."
        )


__all__ = [
    "build_workbook_bytes",
    "raw_csv_bytes",
    "render",
]
