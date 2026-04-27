"""Source selector + auto-calculated page range.

For every configured source, render a checkbox and a pair of numeric
inputs for Start/End page. ``End page`` defaults to
``source.avg_page_per_month × months_span`` so the user gets a sensible
auto-suggestion they can still override.

Iter 12: ``end_page`` auto-recalculates whenever ``months_span`` changes
(i.e. whenever the user picks a new Time Range). Within a stable time
range, manual edits to End Page persist; selecting a new time range
forces a re-snap to the freshly-computed auto value.
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
        end_key = f"{base_key}_end"
        prev_span_key = f"{base_key}_prev_span"
        auto_end = max(1, src.avg_page_per_month * months_span)

        # Re-snap End Page to the freshly-computed auto value whenever the
        # months_span has changed (i.e. the user picked a new time range).
        # Setting ``st.session_state[end_key]`` BEFORE the widget renders
        # makes Streamlit honour the new default — otherwise ``value=`` is
        # ignored on subsequent renders. Within a stable time range, this
        # branch doesn't fire and the user's manual edit persists.
        if st.session_state.get(prev_span_key) != months_span:
            st.session_state[end_key] = auto_end
            st.session_state[prev_span_key] = months_span

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
                step=1,
                key=end_key,
                help=(
                    f"Auto-recalc on time range change: "
                    f"{src.avg_page_per_month} pages/month × {months_span} "
                    f"month(s) = {auto_end}. Edit to override; the next "
                    f"time-range change will re-snap."
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
