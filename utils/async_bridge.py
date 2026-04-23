"""Bridge between Streamlit's main thread and the engine's worker thread.

Streamlit's script-runner is single-threaded per session: calling
``engine.run`` directly from the script would freeze the UI until every
source finished. We instead spin up **one** dedicated background thread
that calls ``engine.run`` — it owns the executor pool internally — and
the UI polls the ``ProgressBus`` between reruns.

``add_script_run_ctx()`` isn't needed by the worker itself (the worker
must never call ``st.*``) but is left available here for components that
want to hop back to Streamlit land (e.g. a future notification callback).
"""

from __future__ import annotations

import threading

from scraper.engine import EngineRunSpec, run
from scraper.progress import ProgressBus
from scraper.runner import SourceRunResult


class JobHandle:
    """What the UI stashes in ``st.session_state`` while a scrape is running.

    The three pieces the UI needs: the bus (to poll for progress), a way
    to read results after completion, and a way to cancel.
    """

    def __init__(self, bus: ProgressBus) -> None:
        self.bus = bus
        self._results: list[SourceRunResult] | None = None
        self._thread: threading.Thread | None = None
        self._error: BaseException | None = None

    @property
    def results(self) -> list[SourceRunResult] | None:
        return self._results

    @property
    def error(self) -> BaseException | None:
        return self._error

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def cancel(self) -> None:
        self.bus.cancel()

    def wait(self, timeout: float | None = None) -> None:
        """Block until the background thread finishes. Tests use this."""
        if self._thread is not None:
            self._thread.join(timeout)


def start_engine_thread(spec: EngineRunSpec) -> JobHandle:
    """Spawn a worker thread running the engine and return a ``JobHandle``.

    The thread is daemonised so it can't block interpreter shutdown if the
    Streamlit server is killed mid-scrape. Errors on the worker are
    captured onto the handle rather than propagated, so the UI can surface
    them without the whole session crashing.
    """
    bus = ProgressBus()
    handle = JobHandle(bus)

    def _target() -> None:
        try:
            handle._results = run(spec, bus=bus)
        except BaseException as e:  # noqa: BLE001 - we re-surface via handle
            handle._error = e
            # Mark the run as finished so the UI can stop polling.
            from scraper.progress import RunFinished

            bus.emit(RunFinished(total_items=0, cancelled=True))

    t = threading.Thread(target=_target, name="engine-driver", daemon=True)
    handle._thread = t
    t.start()
    return handle


__all__ = ["JobHandle", "start_engine_thread"]
