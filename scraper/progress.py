"""Thread-safe progress bus for scraping jobs.

A ``ProgressBus`` is the one-way communication channel between the background
scraping thread(s) and whoever is observing — the Streamlit UI in production,
a test assertion list in unit tests, or nothing at all.

Design constraints:
- No Streamlit imports: the bus has to stay consumable from any thread, not
  just Streamlit's main thread.
- Non-blocking reads: the UI polls and must never block on an empty bus.
- Cancellation: the UI's "Stop" button sets a flag the runner checks between
  pages, so an in-flight HTTP request finishes cleanly rather than being
  killed mid-socket.
- Immutable events: every event is a frozen dataclass. The bus is append-only
  from the producer's side; the consumer drains the queue on each poll.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass

from scraper.runner import SourceRunResult

# --------------------------------------------------------------------------- #
# Event types
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RunStarted:
    source_names: list[str]
    total_pages_planned: int


@dataclass(frozen=True)
class SourceStarted:
    source_name: str
    total_pages: int


@dataclass(frozen=True)
class PageFetched:
    source_name: str
    page: int
    items_scanned: int
    items_in_range: int
    # Iter 8: which layer delivered this page. ``None`` for the browser
    # runner (``run_browser_source``) where the persistent Playwright
    # session is not part of the single-shot fallback cascade.
    layer_used: int | None = None


@dataclass(frozen=True)
class PageFailed:
    source_name: str
    page: int
    error: str


@dataclass(frozen=True)
class SourceFinished:
    source_name: str
    result: SourceRunResult


@dataclass(frozen=True)
class RunFinished:
    total_items: int
    cancelled: bool


Event = RunStarted | SourceStarted | PageFetched | PageFailed | SourceFinished | RunFinished


# --------------------------------------------------------------------------- #
# Bus
# --------------------------------------------------------------------------- #


class ProgressBus:
    """Append-only queue of ``Event``s + a cooperative cancellation flag."""

    def __init__(self) -> None:
        self._queue: queue.Queue[Event] = queue.Queue()
        self._cancelled = threading.Event()
        self._finished = threading.Event()

    # -- producer side ------------------------------------------------------- #

    def emit(self, event: Event) -> None:
        self._queue.put(event)
        if isinstance(event, RunFinished):
            self._finished.set()

    # -- cancellation -------------------------------------------------------- #

    def cancel(self) -> None:
        """Signal the background runner(s) to stop at the next safe boundary."""
        self._cancelled.set()

    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    # -- consumer side ------------------------------------------------------- #

    def drain(self) -> list[Event]:
        """Return all events queued since the last drain, without blocking."""
        out: list[Event] = []
        while True:
            try:
                out.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return out

    def is_finished(self) -> bool:
        """True once a ``RunFinished`` event has been emitted."""
        return self._finished.is_set()


__all__ = [
    "Event",
    "PageFailed",
    "PageFetched",
    "ProgressBus",
    "RunFinished",
    "RunStarted",
    "SourceFinished",
    "SourceStarted",
]
