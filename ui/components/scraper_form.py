"""Scraper CRUD UI component used by the Settings page.

Renders a list of existing sources (collapsible) and a full create/edit form
for a single source, with dynamic fields based on the chosen pagination type.
Also hosts the ``Test Selector`` tool that runs one Layer 1 fetch.

Iter 12 refinements:

- ``Allowed layers`` multiselect uses semantic labels ("Layer 1: HTTPX/Fast"
  …) via a ``format_func``. The Pydantic model still stores the raw integer
  list — this is purely a presentation concern.
- Save / upload / delete actions surface inline ``st.success`` /
  ``st.error`` / ``st.warning`` banners so the user gets explicit
  confirmation of every mutation.
- Delete uses a two-step confirmation pattern: the first click flips a
  session-state flag and changes the button label to
  "⚠️ Click again to confirm delete"; the second click executes.
- Test Selector default URL pulls from the live form's ``url_template``,
  with a sensible fallback for fresh sources.
- Test Selector output is broken out per selector (container / title /
  link / date) with explicit pass/fail status and sample values.
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
from scraper.models import SelectorCheck, TestSelectorResult
from scraper.selector_tester import run_selector_test

_PAGINATION_OPTIONS: tuple[str, ...] = ("url_params", "infinite_scroll", "click_next")
_LAYER_OPTIONS: tuple[ScrapeLayer, ...] = (1, 2, 3, 4)
#: Human-readable labels for the multiselect. Backend logic still consumes
#: the raw integer list — this map is presentation-only.
_LAYER_LABELS: dict[ScrapeLayer, str] = {
    1: "Layer 1: HTTPX/Fast",
    2: "Layer 2: Selectolax/Mobile",
    3: "Layer 3: Playwright",
    4: "Layer 4: Stealth",
}

#: Session-state key prefix for short-lived inline status banners. Each
#: entry maps to a ``(level, message)`` tuple consumed once on the next
#: render (status banners survive ``st.rerun()`` so the user sees the
#: confirmation after the form re-loads).
_STATUS_KEY = "scraper_form_status"

_FALLBACK_TEST_URL = "https://example.com/indeks?page=1"


def _flash(level: str, message: str) -> None:
    """Stage a status banner that survives the next ``st.rerun()``."""
    st.session_state[_STATUS_KEY] = (level, message)


def _consume_status() -> None:
    """Render and discard any pending status banner from a prior action."""
    pending = st.session_state.pop(_STATUS_KEY, None)
    if pending is None:
        return
    level, message = pending
    if level == "success":
        st.success(message)
    elif level == "error":
        st.error(message)
    elif level == "warning":
        st.warning(message)
    else:
        st.info(message)


def _layer_label(layer: ScrapeLayer) -> str:
    return _LAYER_LABELS.get(layer, f"Layer {layer}")


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


def _resolve_test_default_url(url_template: str) -> str:
    """Apply ``{page}=1`` to the live URL template; fall back if blank."""
    candidate = (url_template or "").replace("{page}", "1").strip()
    return candidate or _FALLBACK_TEST_URL


def _render_check(check: SelectorCheck) -> None:
    """Render one per-selector outcome (pass with samples, or explicit fail)."""
    label = check.name.capitalize()
    if check.matched:
        body = f"**{label}** — `{check.selector}` matched."
        if check.samples:
            preview = " · ".join(s if len(s) <= 80 else s[:77] + "…" for s in check.samples)
            body += f" Sample(s): {preview}"
        if check.error:
            # Soft fail: the selector matched some containers but missed others.
            st.warning(f"{body}\n\nWarning: {check.error}")
        else:
            st.success(body)
    else:
        msg = check.error or f"{label} selector '{check.selector}' did not match."
        st.warning(f"**{label}** — {msg}")


def _render_test_selector_output(result: TestSelectorResult) -> None:
    """Render a granular per-selector breakdown plus the items preview."""
    if not result.ok:
        st.error(f"Fetch failed via {result.layer}: {result.error}")
        return

    st.success(f"Fetched {result.url} (HTTP {result.status_code}) via {result.layer}")
    st.caption("Per-selector breakdown:")
    for check in result.checks:
        _render_check(check)

    if not result.items:
        st.warning(
            "Zero rows passed all four selectors. Inspect the per-selector "
            "warnings above, then adjust the failing selector(s) and retry."
        )
        return

    st.caption(f"Preview of the first {min(10, len(result.items))} extracted row(s):")
    st.dataframe(
        pd.DataFrame(
            [
                {"Title": i.title, "Link": i.link, "Date (raw)": i.date_raw}
                for i in result.items[:10]
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )


def _render_test_selector(source: ScrapeSource, form_key: str) -> None:
    st.markdown("**Test Selector**")
    st.caption(
        "Runs a single Layer 1 (httpx + BeautifulSoup) fetch against the URL you "
        "provide, then shows the raw container / title / link / date hits found "
        "by your selectors. Default URL tracks the source's URL template."
    )
    expected_default = _resolve_test_default_url(source.url_template)

    # Push the default into session state whenever the source's URL template
    # changes, so switching sources or editing the template visibly updates
    # the test URL field. The previously-applied default is tracked so we
    # don't clobber the user's manual edits within a stable template.
    test_url_key = "scraper_test_url"
    last_default_key = "scraper_test_url_last_default"
    if st.session_state.get(last_default_key) != expected_default:
        st.session_state[test_url_key] = expected_default
        st.session_state[last_default_key] = expected_default

    test_url = st.text_input("Test URL", key=test_url_key)
    if st.button("Run Test Selector", key=f"{form_key}_test_run"):
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
            st.warning(
                "Cannot run Test Selector — the following selector(s) are empty: "
                + ", ".join(missing)
                + ". Fill them in above and try again."
            )
            return
        if not test_url.strip():
            st.warning("Test URL is empty. Provide a fully-qualified URL and try again.")
            return
        with st.spinner("Fetching…"):
            result = run_selector_test(test_url, source.selectors)
        _render_test_selector_output(result)


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
            format_func=_layer_label,
            help=(
                "Engine tries these in ascending order; falls through on failure. "
                "Layer 1 is fastest (HTTPX); Layer 4 is slowest but evades the "
                "most aggressive bot-detection."
            ),
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

    # Two-step delete confirmation: first click flips the confirm flag and
    # relabels the button; second click within the same session executes.
    confirm_key = f"{form_key}_delete_confirm"
    pending_confirm = bool(st.session_state.get(confirm_key))
    delete_label = "⚠️ Click again to confirm delete" if pending_confirm else "Delete this source"
    delete_clicked = (
        col_delete.button(
            delete_label,
            type="secondary",
            key=f"{form_key}_delete",
        )
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
    _render_test_selector(live_draft, form_key)

    if save_clicked:
        if not name.strip():
            st.error("Source name is required — fix and click Save again.")
            return
        if not container_sel or not title_sel or not link_sel or not date_sel:
            st.error(
                "All four selectors (container / title / link / date) are required. "
                "Fill them in and click Save again."
            )
            return
        new_list = list(sources)
        if is_new:
            if any(s.name == name for s in new_list):
                st.error(f"A source named '{name}' already exists — pick a different name.")
                return
            new_list.append(live_draft)
        else:
            assert edit_idx is not None
            new_list[edit_idx] = live_draft
        save_sources(new_list)
        # Stage a banner that survives the next st.rerun().
        _flash(
            "success",
            f"Saved source '{name}'. {len(new_list)} source(s) now configured.",
        )
        st.session_state.pop(confirm_key, None)
        st.rerun()

    if delete_clicked and edit_idx is not None:
        if not pending_confirm:
            st.session_state[confirm_key] = True
            st.warning(
                f"Delete '{draft.name}'? This is permanent. Click the red button "
                "again to confirm, or click anywhere else to cancel."
            )
            return
        new_list = [s for i, s in enumerate(sources) if i != edit_idx]
        save_sources(new_list)
        st.session_state.pop(confirm_key, None)
        _flash("success", f"Deleted source '{draft.name}'.")
        st.rerun()


def render() -> None:
    sources = load_sources()
    _consume_status()
    st.caption(f"{len(sources)} source(s) configured.")
    if sources:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Name": s.name,
                        "Pagination": s.pagination_type,
                        "URL template": s.url_template,
                        "Layers": ", ".join(_layer_label(x) for x in s.enabled_layers),
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
