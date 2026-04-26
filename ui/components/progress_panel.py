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
        if handle is not None and handle.error is not None:
            st.error(f"Worker thread crashed: {handle.error!r}")


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
    "render",
    "reset_snapshot",
]
