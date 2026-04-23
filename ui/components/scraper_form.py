"""Scraper CRUD UI component used by the Settings page.

Renders a list of existing sources (collapsible) and a full create/edit form
for a single source, with dynamic fields based on the chosen pagination type.
Also hosts the ``Test Selector`` tool that runs one Layer 1 fetch.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from config import (
    ScrapeLayer,
    ScraperSelectors,
    ScrapeSource,
    SleepRange,
    load_sources,
    save_sources,
)
from scraper.selector_tester import run_selector_test

_PAGINATION_OPTIONS: tuple[str, ...] = ("url_params", "infinite_scroll", "click_next")
_LAYER_OPTIONS: tuple[ScrapeLayer, ...] = (1, 2, 3, 4)


def _blank_source() -> ScrapeSource:
    return ScrapeSource(
        name="",
        pagination_type="url_params",
        url_template="https://example.com/indeks?page={page}",
        selectors=ScraperSelectors(container="", title="", link="", date=""),
    )


def _pick_source_for_edit(sources: list[ScrapeSource]) -> tuple[int | None, ScrapeSource]:
    """Return (index-or-None, source-to-edit). None index == creating a new source."""
    options = ["<new>"] + [s.name for s in sources]
    choice = st.selectbox("Edit existing or add new", options=options, key="scraper_edit_pick")
    if choice == "<new>":
        return None, _blank_source()
    idx = options.index(choice) - 1
    return idx, sources[idx].model_copy(deep=True)


def _render_test_selector(source: ScrapeSource) -> None:
    st.markdown("**Test Selector**")
    st.caption(
        "Runs a single Layer 1 (httpx + BeautifulSoup) fetch against the URL you "
        "provide, then shows the raw title/link/date hits found by your selectors."
    )
    default_url = source.url_template.replace("{page}", "1")
    test_url = st.text_input("Test URL", value=default_url, key="scraper_test_url")
    if st.button("Run Test Selector", key="scraper_test_run"):
        missing = [
            f
            for f, v in (
                ("container", source.selectors.container),
                ("title", source.selectors.title),
                ("link", source.selectors.link),
                ("date", source.selectors.date),
            )
            if not v.strip()
        ]
        if missing:
            st.error(
                "Cannot run Test Selector — the following selector(s) are empty: "
                + ", ".join(missing)
                + ". Fill them in above and try again."
            )
            return
        with st.spinner("Fetching…"):
            result = run_selector_test(test_url, source.selectors)
        if not result.ok:
            st.error(f"Fetch failed via {result.layer}: {result.error}")
            return
        st.success(f"Fetched {result.url} (HTTP {result.status_code}) via {result.layer}")
        if not result.items:
            st.warning(
                "Zero items matched — your container / title / link / date selectors "
                "probably need adjustment. Inspect the page in DevTools and retry."
            )
            return
        st.dataframe(
            pd.DataFrame(
                [{"Title": i.title, "Link": i.link, "Date (raw)": i.date_raw} for i in result.items]
            ),
            use_container_width=True,
            hide_index=True,
        )


def _render_form(sources: list[ScrapeSource]) -> None:
    edit_idx, draft = _pick_source_for_edit(sources)
    is_new = edit_idx is None

    # NOTE: intentionally NOT wrapped in st.form — we want the Test Selector
    # button (rendered below) to see live widget values without requiring the
    # user to Save first.
    form_key = f"scraper_{'new' if is_new else edit_idx}"
    c1, c2 = st.columns(2)
    with c1:
        name = st.text_input("Source name", value=draft.name, key=f"{form_key}_name")
        url_template = st.text_input(
            "URL template", value=draft.url_template, key=f"{form_key}_url"
        )
        pagination_type = st.selectbox(
            "Pagination type",
            options=_PAGINATION_OPTIONS,
            index=_PAGINATION_OPTIONS.index(draft.pagination_type),
            key=f"{form_key}_pag",
        )
        avg_page_per_month = st.number_input(
            "Avg pages / month",
            min_value=1,
            value=draft.avg_page_per_month,
            step=1,
            key=f"{form_key}_avg",
        )
    with c2:
        enabled = st.checkbox(
            "Enabled on dashboard", value=draft.enabled, key=f"{form_key}_enabled"
        )
        max_retries = st.number_input(
            "Max retries",
            min_value=0,
            value=draft.max_retries,
            step=1,
            key=f"{form_key}_retries",
        )
        min_sleep = st.number_input(
            "Min sleep (sec)",
            min_value=0.0,
            value=float(draft.sleep.min),
            step=0.5,
            key=f"{form_key}_min",
        )
        max_sleep = st.number_input(
            "Max sleep (sec)",
            min_value=0.0,
            value=float(draft.sleep.max),
            step=0.5,
            key=f"{form_key}_max",
        )
        enabled_layers = st.multiselect(
            "Allowed layers",
            options=_LAYER_OPTIONS,
            default=list(draft.enabled_layers),
            help="Engine tries these in ascending order; falls through on failure.",
            key=f"{form_key}_layers",
        )

    st.markdown("**Selectors**")
    s1, s2 = st.columns(2)
    with s1:
        container_sel = st.text_input(
            "Container", value=draft.selectors.container, key=f"{form_key}_container"
        )
        title_sel = st.text_input("Title", value=draft.selectors.title, key=f"{form_key}_title")
    with s2:
        link_sel = st.text_input("Link", value=draft.selectors.link, key=f"{form_key}_link")
        date_sel = st.text_input("Date", value=draft.selectors.date, key=f"{form_key}_date")

    next_button_sel = ""
    scrolls_per_page = draft.scrolls_per_page
    if pagination_type == "click_next":
        next_button_sel = st.text_input(
            "Next-button selector",
            value=draft.selectors.next_button or "",
            help="CSS/XPath for the 'Next Page' button (Playwright will click this).",
            key=f"{form_key}_nextbtn",
        )
    elif pagination_type == "infinite_scroll":
        scrolls_per_page = st.number_input(
            "Scrolls per logical page",
            min_value=1,
            value=draft.scrolls_per_page,
            step=1,
            key=f"{form_key}_scrolls",
        )

    col_save, col_delete = st.columns([1, 1])
    save_clicked = col_save.button("Save", type="primary", key=f"{form_key}_save")
    delete_clicked = (
        col_delete.button("Delete this source", type="secondary", key=f"{form_key}_delete")
        if not is_new
        else False
    )

    # Reconstruct a ScrapeSource in-place for the Test Selector helper, using
    # whatever the user has entered in the form right now.
    live_draft = ScrapeSource(
        name=name or "(unnamed)",
        pagination_type=pagination_type,
        url_template=url_template or draft.url_template,
        selectors=ScraperSelectors(
            container=container_sel,
            title=title_sel,
            link=link_sel,
            date=date_sel,
            next_button=next_button_sel or None,
        ),
        avg_page_per_month=int(avg_page_per_month),
        sleep=SleepRange(min=float(min_sleep), max=max(float(max_sleep), float(min_sleep))),
        max_retries=int(max_retries),
        enabled_layers=list(enabled_layers) if enabled_layers else [1, 3],
        scrolls_per_page=int(scrolls_per_page),
        enabled=enabled,
    )
    _render_test_selector(live_draft)

    if save_clicked:
        if not name.strip():
            st.error("Source name is required.")
            return
        if not container_sel or not title_sel or not link_sel or not date_sel:
            st.error("All four selectors (container/title/link/date) are required.")
            return
        new_list = list(sources)
        if is_new:
            if any(s.name == name for s in new_list):
                st.error(f"A source named '{name}' already exists.")
                return
            new_list.append(live_draft)
        else:
            assert edit_idx is not None
            new_list[edit_idx] = live_draft
        save_sources(new_list)
        st.success(f"Saved source '{name}'.")
        st.rerun()

    if delete_clicked and edit_idx is not None:
        new_list = [s for i, s in enumerate(sources) if i != edit_idx]
        save_sources(new_list)
        st.success(f"Deleted source '{draft.name}'.")
        st.rerun()


def render() -> None:
    sources = load_sources()
    st.caption(f"{len(sources)} source(s) configured.")
    if sources:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Name": s.name,
                        "Pagination": s.pagination_type,
                        "URL template": s.url_template,
                        "Layers": ", ".join(str(x) for x in s.enabled_layers),
                        "Enabled": s.enabled,
                    }
                    for s in sources
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
    _render_form(sources)


__all__ = ["render"]
