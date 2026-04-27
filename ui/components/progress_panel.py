"""Live progress panel.

Reads events from a background ``ProgressBus`` and renders overall + per-source
progress bars. Uses ``st.fragment(run_every=...)`` so only this panel re-runs
while the scrape is in progress — the rest of the page stays interactive.

A ``ProgressSnapshot`` in ``st.session_state`` accumulates what we've seen so
far; the bus itself is drained destructively on each poll. This means if the
user navigates away and back the snapshot still reflects everything that
happened while they were gone.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import streamlit as st

from scraper.progress import (
    Event,
    PageFailed,
    PageFetched,
    RunFinished,
    RunStarted,
    SourceFinished,
    SourceStarted,
)
from utils.async_bridge import JobHandle

K_PROGRESS_SNAPSHOT = "progress_snapshot"
K_JOB_HANDLE = "job_handle"
K_FRAGMENT_SAW_FINISHED = "progress_fragment_saw_finished"


@dataclass
class SourceSummary:
    """Per-source roll-up surfaced in the post-scrape detail panel.

    Populated when a ``SourceFinished`` event arrives so the UI can show
    early-stopping reasons, page failures, and selector-miss signals
    without having to re-iterate the events.
    """

    source_name: str
    pages_scanned: int
    pages_failed: int
    items_in_range: int
    early_stopped: bool
    early_stop_reason: str | None
    page_failures: list[dict[str, str]] = field(default_factory=list)
    pages_with_zero_hits: int = 0


@dataclass
class ProgressSnapshot:
    """Accumulated view of a run — mutated as bus events arrive."""

    started: bool = False
    finished: bool = False
    cancelled: bool = False
    sources_total: int = 0
    sources_done: int = 0
    total_items: int = 0
    per_source_pages_done: dict[str, int] = field(default_factory=dict)
    per_source_pages_total: dict[str, int] = field(default_factory=dict)
    per_source_items: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    # Iter 10: which layer served each successful page, aggregated across
    # all sources. Populated from ``SourceFinished.result.stats.layer_usage``
    # when each source finishes. Surfaces the Iter 8 / Iter 9 cascade
    # transparently on the completion banner without hijacking the runtime
    # event stream (which would require a new event type).
    layer_usage: dict[int, int] = field(default_factory=dict)
    # Iter 12: per-source summaries used for the post-scrape detail panel.
    source_summaries: list[SourceSummary] = field(default_factory=list)


def _apply_events(snap: ProgressSnapshot, events: list[Event]) -> None:
    for ev in events:
        if isinstance(ev, RunStarted):
            snap.started = True
            snap.sources_total = len(ev.source_names)
            for name in ev.source_names:
                snap.per_source_pages_done.setdefault(name, 0)
                snap.per_source_pages_total.setdefault(name, 0)
                snap.per_source_items.setdefault(name, 0)
        elif isinstance(ev, SourceStarted):
            snap.per_source_pages_total[ev.source_name] = ev.total_pages
        elif isinstance(ev, PageFetched):
            snap.per_source_pages_done[ev.source_name] = (
                snap.per_source_pages_done.get(ev.source_name, 0) + 1
            )
            snap.per_source_items[ev.source_name] = (
                snap.per_source_items.get(ev.source_name, 0) + ev.items_in_range
            )
        elif isinstance(ev, PageFailed):
            snap.per_source_pages_done[ev.source_name] = (
                snap.per_source_pages_done.get(ev.source_name, 0) + 1
            )
            snap.errors.append(f"{ev.source_name} page {ev.page}: {ev.error}")
        elif isinstance(ev, SourceFinished):
            snap.sources_done += 1
            # Aggregate this source's per-layer page counts into the run total.
            for layer_num, count in ev.result.stats.layer_usage.items():
                snap.layer_usage[layer_num] = snap.layer_usage.get(layer_num, 0) + count
            stats = ev.result.stats
            snap.source_summaries.append(
                SourceSummary(
                    source_name=stats.source_name,
                    pages_scanned=stats.pages_scanned,
                    pages_failed=stats.pages_failed,
                    items_in_range=stats.items_in_range,
                    early_stopped=stats.early_stopped,
                    early_stop_reason=stats.early_stop_reason,
                    page_failures=list(stats.page_failures),
                    pages_with_zero_hits=stats.pages_with_zero_hits,
                )
            )
        elif isinstance(ev, RunFinished):
            snap.finished = True
            snap.cancelled = ev.cancelled
            snap.total_items = ev.total_items


def _ensure_snapshot() -> ProgressSnapshot:
    snap = st.session_state.get(K_PROGRESS_SNAPSHOT)
    if not isinstance(snap, ProgressSnapshot):
        snap = ProgressSnapshot()
        st.session_state[K_PROGRESS_SNAPSHOT] = snap
    return snap


def reset_snapshot() -> None:
    """Called when the user kicks off a new run."""
    st.session_state[K_PROGRESS_SNAPSHOT] = ProgressSnapshot()
    # Arm the "saw finished" sentinel so the fragment fires a full rerun
    # exactly once when this fresh run transitions to the finished state.
    st.session_state[K_FRAGMENT_SAW_FINISHED] = False


def _overall_fraction(snap: ProgressSnapshot) -> float:
    total_pages = sum(snap.per_source_pages_total.values())
    if total_pages <= 0:
        return 0.0 if not snap.finished else 1.0
    done_pages = sum(snap.per_source_pages_done.values())
    return min(1.0, done_pages / total_pages)


def _render_panel(snap: ProgressSnapshot, handle: JobHandle | None) -> None:
    if not snap.started and handle is None:
        st.caption("Click **Start Scraping** to begin.")
        return

    overall = _overall_fraction(snap)
    overall_label = (
        "Cancelled"
        if snap.cancelled
        else (
            "Completed"
            if snap.finished
            else f"Running · {snap.sources_done}/{snap.sources_total} sources done"
        )
    )
    st.progress(overall, text=f"Overall: {overall_label} ({overall * 100:.0f}%)")

    if handle is not None and handle.is_running() and st.button("Stop", key="progress_panel_stop"):
        handle.cancel()
        st.warning("Stop requested — running sources will halt at the next page boundary.")

    with st.expander("Per-source progress", expanded=True):
        for src_name in snap.per_source_pages_total:
            done = snap.per_source_pages_done.get(src_name, 0)
            total = snap.per_source_pages_total.get(src_name, 0)
            items = snap.per_source_items.get(src_name, 0)
            frac = (done / total) if total > 0 else 0.0
            st.progress(
                min(1.0, frac),
                text=f"**{src_name}** — {done}/{total} pages · {items} items in range",
            )

    if snap.errors:
        with st.expander(f"Errors ({len(snap.errors)})"):
            for err in snap.errors:
                st.text(err)

    if snap.finished:
        if snap.cancelled:
            st.info(f"Run cancelled. Collected {snap.total_items} items before stopping.", icon="⏹️")
        else:
            st.success(f"Run complete. {snap.total_items} items in range.", icon="✅")
        # Iter 10: show which fallback layer served how many pages so the
        # user can see the Iter 8 / Iter 9 cascade in action.
        if snap.layer_usage:
            parts = [f"L{n}={snap.layer_usage[n]}" for n in sorted(snap.layer_usage)]
            st.caption(f"Layer usage: {', '.join(parts)}")
        # Iter 12: detailed post-scrape summary — one expander per source
        # surfacing early-stopping reasons, per-page failures, and
        # selector-miss signals so the user can diagnose without grepping
        # the engine logs.
        _render_post_scrape_summary(snap)
        if handle is not None and handle.error is not None:
            st.error(f"Worker thread crashed: {handle.error!r}")


def _render_post_scrape_summary(snap: ProgressSnapshot) -> None:
    """Render a per-source detail panel after a run completes.

    Each source gets one ``st.expander`` that summarises the three things
    the user most often wants to know after a run:

    1. Did this source early-stop, and why? (date-window-exceeded marker)
    2. Did any specific pages fail, and what was the error?
    3. Were the selectors silently broken? (zero-hit pages signal a likely
       container-selector mismatch — distinct from a network failure.)

    The panel only renders when at least one source produced a noteworthy
    signal; an entirely-clean run keeps the UI uncluttered.
    """
    if not snap.source_summaries:
        return

    notable = [
        s
        for s in snap.source_summaries
        if s.early_stopped or s.page_failures or s.pages_with_zero_hits
    ]
    if not notable and not any(s.pages_scanned > 0 for s in snap.source_summaries):
        return

    label = (
        "Run summary — every source clean"
        if not notable
        else f"Run summary — {len(notable)} source(s) with notable events"
    )
    with st.expander(label, expanded=bool(notable)):
        for summary in snap.source_summaries:
            st.markdown(f"**{summary.source_name}**")
            cols = st.columns(4)
            cols[0].metric("Pages scanned", summary.pages_scanned)
            cols[1].metric("Pages failed", summary.pages_failed)
            cols[2].metric("Items in range", summary.items_in_range)
            cols[3].metric(
                "Zero-hit pages",
                summary.pages_with_zero_hits,
                help=(
                    "Successful fetches that returned 0 rows. A non-zero "
                    "count usually means the container selector is "
                    "mismatched on this source."
                ),
            )

            if summary.early_stopped and summary.early_stop_reason:
                st.info(
                    f"⏱ Early-stopped on {summary.early_stop_reason}",
                    icon="⏱️",
                )
            elif summary.early_stopped:
                st.info("⏱ Early-stopped (date range exceeded).", icon="⏱️")

            if summary.page_failures:
                st.warning(
                    f"⚠️ {len(summary.page_failures)} page failure(s):",
                    icon="⚠️",
                )
                for pf in summary.page_failures:
                    st.text(
                        f"  · page {pf.get('page', '?')} "
                        f"({pf.get('url', '')}): {pf.get('error', '')}"
                    )

            if summary.pages_with_zero_hits:
                st.warning(
                    f"⚠️ {summary.pages_with_zero_hits} page(s) fetched but "
                    "returned zero rows. Re-check the container selector "
                    "for this source in **Settings → Scraper Configuration**.",
                    icon="🔍",
                )

            if not (summary.early_stopped or summary.page_failures or summary.pages_with_zero_hits):
                st.caption(
                    "No notable events for this source — "
                    f"{summary.items_in_range} item(s) in range."
                )
            st.divider()


@st.fragment(run_every=0.5)
def _live_fragment() -> None:
    snap = _ensure_snapshot()
    handle: JobHandle | None = st.session_state.get(K_JOB_HANDLE)
    was_finished = st.session_state.get(K_FRAGMENT_SAW_FINISHED, False)
    if handle is not None:
        _apply_events(snap, handle.bus.drain())
    _render_panel(snap, handle)
    # When a run transitions to finished from *inside* the fragment, the
    # fragment rerun scope prevents the main dashboard's render() — and
    # therefore ``_collect_items_if_finished`` + the Results tabs — from
    # re-executing. Kick a full-page rerun exactly once so the Results
    # section picks up the new items.
    if snap.finished and not was_finished:
        st.session_state[K_FRAGMENT_SAW_FINISHED] = True
        st.rerun(scope="app")


def render() -> None:
    """Public entrypoint used by the Main Dashboard."""
    snap = _ensure_snapshot()
    handle: JobHandle | None = st.session_state.get(K_JOB_HANDLE)
    # If nothing is running and nothing has ever run, no need to auto-refresh.
    if handle is None or (snap.finished and not handle.is_running()):
        # Drain any final events first so we render the last frame.
        if handle is not None:
            _apply_events(snap, handle.bus.drain())
        _render_panel(snap, handle)
        return
    _live_fragment()


__all__ = [
    "K_JOB_HANDLE",
    "K_PROGRESS_SNAPSHOT",
    "ProgressSnapshot",
    "SourceSummary",
    "render",
    "reset_snapshot",
]
