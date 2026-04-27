"""Persistent run history.

A small JSON-on-disk log of recent scrape runs so the user can answer
"did this morning's run hit any blocks?" without re-running. The engine
appends one entry per completed run via :func:`append_entry`; the
Main Dashboard renders the last N entries via the
``run_history_panel`` component.

Design constraints:

- **Cap the file size.** We keep at most ``MAX_ENTRIES`` entries (newest
  first); older entries fall off the end. This keeps the file small and
  the dashboard render fast — nobody wants to scroll through 500 runs.
- **Items are not stored.** The history is metadata-only (counts,
  durations, layer usage, errors). Storing every ``NewsItem`` would
  balloon the on-disk footprint and duplicate the export workflow from
  Iter 10. If a user wants the items, they re-run or open the saved
  ``.xlsx``.
- **Atomic writes.** Reuses :func:`utils.io.atomic_write_text` so a crash
  mid-write can never corrupt the history file.
- **Best-effort persistence.** :func:`append_entry` swallows I/O errors
  and logs them — a disk-full event must never crash a successful scrape.
- **Zero Streamlit imports.** Same constraint as the rest of ``scraper/``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from config.paths import config_dir
from utils.io import atomic_write_text, read_text_or_default

logger = logging.getLogger(__name__)

#: Maximum number of entries kept on disk. Older entries are dropped on
#: append. Empirically, 50 is enough to cover roughly a fortnight of
#: hand-driven runs without bloating the file past a few KB.
MAX_ENTRIES = 50

#: Per-entry cap on the number of error lines stored verbatim. Keeps a
#: pathological run (every page on every source failing) from dominating
#: the file. Excess errors are summarised in :attr:`RunHistoryEntry.error_count`
#: which always reflects the true total.
MAX_ERRORS_PER_ENTRY = 20


def history_path() -> Path:
    """Filesystem location of the history file (alongside other configs)."""
    return config_dir() / "run_history.json"


class RunHistoryEntry(BaseModel):
    """One row in the history log."""

    model_config = ConfigDict(extra="forbid")

    started_at: datetime
    finished_at: datetime
    source_names: list[str] = Field(default_factory=list)
    total_items: int = 0
    pages_scanned: int = 0
    pages_failed: int = 0
    layer_usage: dict[int, int] = Field(default_factory=dict)
    cancelled: bool = False
    #: True total error count across all sources (may exceed
    #: ``len(error_lines)`` when truncated).
    error_count: int = 0
    error_lines: list[str] = Field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        return max(0.0, (self.finished_at - self.started_at).total_seconds())

    def layer_usage_summary(self) -> str:
        """Render ``layer_usage`` as a compact ``L1=10, L2=2`` string."""
        if not self.layer_usage:
            return "(none)"
        return ", ".join(f"L{n}={self.layer_usage[n]}" for n in sorted(self.layer_usage))


def load_entries() -> list[RunHistoryEntry]:
    """Return all stored entries, newest first."""
    raw = read_text_or_default(history_path(), default='{"entries": []}')
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.exception("run_history file is corrupt; treating as empty")
        return []
    out: list[RunHistoryEntry] = []
    for item in data.get("entries", []):
        try:
            out.append(RunHistoryEntry.model_validate(item))
        except Exception:
            # Skip malformed entries (e.g. schema changes between releases)
            # rather than failing the whole load.
            logger.exception("skipping malformed run_history entry")
    return out


def _save_entries(entries: list[RunHistoryEntry]) -> None:
    payload = {"entries": [e.model_dump(mode="json") for e in entries]}
    atomic_write_text(history_path(), json.dumps(payload, indent=2, ensure_ascii=False))


def clear_entries() -> int:
    """Atomically wipe the history file. Returns the number of entries removed.

    Surfaced through the dashboard's "Clear History" button (Iter 13).
    Like :func:`append_entry`, this is best-effort — any I/O error is
    logged and swallowed so a corrupt history file can't take the UI
    down. Returns ``0`` on failure for the same reason.
    """
    try:
        before = len(load_entries())
        _save_entries([])
        return before
    except Exception:
        logger.exception("failed to clear run_history; ignoring")
        return 0


def append_entry(entry: RunHistoryEntry) -> None:
    """Add ``entry`` to the head of the history, capping at ``MAX_ENTRIES``.

    Best-effort: any I/O error is logged and swallowed. The caller (the
    engine) must not let a history-write failure bubble up and crash an
    otherwise-successful run.
    """
    try:
        existing = load_entries()
        merged = [entry] + existing
        if len(merged) > MAX_ENTRIES:
            merged = merged[:MAX_ENTRIES]
        _save_entries(merged)
    except Exception:
        logger.exception("failed to append run_history entry; ignoring")


def build_entry_from_results(
    *,
    started_at: datetime,
    finished_at: datetime,
    source_names: list[str],
    results,  # type: ignore[no-untyped-def]  -- avoid circular import at module import time
    cancelled: bool,
) -> RunHistoryEntry:
    """Aggregate per-source ``SourceRunResult`` into a single entry.

    Imports ``SourceRunResult`` lazily to avoid a circular import at module
    load (``scraper.runner`` → ``scraper.run_history`` → ``scraper.runner``).
    """
    total_items = 0
    pages_scanned = 0
    pages_failed = 0
    layer_usage: dict[int, int] = {}
    error_lines: list[str] = []
    error_count = 0
    for result in results:
        stats = result.stats
        total_items += stats.items_in_range
        pages_scanned += stats.pages_scanned
        pages_failed += stats.pages_failed
        for layer_num, count in stats.layer_usage.items():
            layer_usage[layer_num] = layer_usage.get(layer_num, 0) + count
        for line in stats.errors:
            error_count += 1
            if len(error_lines) < MAX_ERRORS_PER_ENTRY:
                error_lines.append(f"{stats.source_name}: {line}")

    return RunHistoryEntry(
        started_at=started_at,
        finished_at=finished_at,
        source_names=source_names,
        total_items=total_items,
        pages_scanned=pages_scanned,
        pages_failed=pages_failed,
        layer_usage=layer_usage,
        cancelled=cancelled,
        error_count=error_count,
        error_lines=error_lines,
    )


__all__ = [
    "MAX_ENTRIES",
    "MAX_ERRORS_PER_ENTRY",
    "RunHistoryEntry",
    "append_entry",
    "build_entry_from_results",
    "clear_entries",
    "history_path",
    "load_entries",
]
