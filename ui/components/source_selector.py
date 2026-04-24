"""Source selector + auto-calculated page range.

For every configured source, render a checkbox and a pair of numeric
inputs for Start/End page. ``End page`` defaults to
``source.avg_page_per_month × months_span`` so the user gets a sensible
auto-suggestion they can still override.
"""

from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from config import ScrapeSource


@dataclass(frozen=True)
class SourceSelection:
    """What the dashboard needs from this component per source."""

    source: ScrapeSource
    selected: bool
    start_page: int
    end_page: int


def render(
    sources: list[ScrapeSource],
    months_span: int,
    key_prefix: str = "ss",
) -> list[SourceSelection]:
    """Render one row per source, returning the full list of selections."""
    if not sources:
        st.info(
            "No scraper sources configured yet. Add one in **Settings → Scraper Configuration**.",
            icon="ℹ️",
        )
        return []

    selections: list[SourceSelection] = []
    for src in sources:
        # Use (name, pagination_type) as a stable widget key so edits to a
        # source's selectors don't reset the checkbox state.
        base_key = f"{key_prefix}_{src.name}"
        default_end = max(1, src.avg_page_per_month * months_span)

        cols = st.columns([3, 1, 1, 2])
        with cols[0]:
            checked = st.checkbox(
                f"**{src.name}**  ·  _{src.pagination_type}_",
                value=src.enabled,
                key=f"{base_key}_checked",
                help=src.url_template,
            )
        with cols[1]:
            start_page = st.number_input(
                "Start",
                min_value=1,
                value=1,
                step=1,
                key=f"{base_key}_start",
            )
        with cols[2]:
            end_page = st.number_input(
                "End",
                min_value=1,
                value=default_end,
                step=1,
                key=f"{base_key}_end",
                help=(
                    f"Auto: {src.avg_page_per_month} pages/month × {months_span} "
                    f"month(s) = {default_end}"
                ),
            )
        with cols[3]:
            layers = ", ".join(f"L{n}" for n in src.enabled_layers)
            st.caption(f"Layers: {layers}")

        selections.append(
            SourceSelection(
                source=src,
                selected=bool(checked),
                start_page=int(start_page),
                end_page=int(end_page),
            )
        )
    return selections


__all__ = ["SourceSelection", "render"]
