# Testing the Main Dashboard end-to-end

This skill documents the repeatable recipe for end-to-end browser testing of the Streamlit Main Dashboard — verifying the full scrape flow without hitting real news portals.

## When to use this skill

- You made UI or scraper-engine changes that surface on the Main Dashboard (progress bars, cancellation, results tables, etc.)
- You want a deterministic end-to-end smoke test with a screen recording
- You need to prove the UI stays responsive during a scrape (non-blocking UI assertion)

## Setup

### 1. Throttled fixture HTTP server

Serve deterministic HTML per `?page=N` request with a 2–3s sleep so progress is observable. Save as `/home/ubuntu/test-plans/fixture_server.py`:

```python
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PAGE = """<!doctype html><html><body><ul class=\"news-list\">
<li class=\"article-item\"><h2><a href=\"/a\">Article A page {page}</a></h2><span class=\"date-time\">5 menit lalu</span></li>
<li class=\"article-item\"><h2><a href=\"/b\">Article B page {page}</a></h2><span class=\"date-time\">5 menit lalu</span></li>
<li class=\"article-item\"><h2><a href=\"/c\">Article C page {page}</a></h2><span class=\"date-time\">5 menit lalu</span></li>
</ul></body></html>"""

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        page = parse_qs(urlparse(self.path).query).get("page", ["1"])[0]
        time.sleep(3.0)
        body = PAGE.format(page=page).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a, **k): pass

ThreadingHTTPServer(("127.0.0.1", 8765), H).serve_forever()
```

Dates of `5 menit lalu` are in-range for "This Month" (today-anchored), so early-stop won't fire.

For deterministic Iter 5/6 categorization/pivot tests, drop the `time.sleep` and emit 5 specific titles designed to exercise include/exclude/explosion (e.g. `Harga BBM dan pertanian naik` for Agri+Energi two-rule match, `Advertorial produk BBM terbaru` for the global-exclude drop).

### 2. Seed `config/sources.json`

Overwrite with one or more sources pointing at the fixture server. Use `sleep={min:0, max:0}` and `max_retries=0` so the run is fast and deterministic. Layer 1 only:

```json
{
  "sources": [
    {
      "name": "PortalX_A",
      "pagination_type": "url_params",
      "url_template": "http://127.0.0.1:8765/news?page={page}",
      "selectors": {"container": "li.article-item", "title": "h2 a", "link": "h2 a", "date": "span.date-time", "next_button": null},
      "avg_page_per_month": 3,
      "sleep": {"min": 0.0, "max": 0.0},
      "max_retries": 0,
      "enabled_layers": [1],
      "scrolls_per_page": 1,
      "enabled": true
    }
  ]
}
```

**Always revert to `{"sources": []}` after testing** — do not commit this file. Same for `config/categorizers.json` (→ `{"groupings": []}`) and `config/app_settings.yaml` (→ `overall_exclude_tokens: []`). `git checkout -- config/sources.json config/categorizers.json config/app_settings.yaml` is the fast way.

Schema gotchas that will cause a `pydantic ValidationError` on dashboard load (and make the whole page red):
- `selectors.container` (not `item_container`).
- `sleep.min` / `sleep.max` (not `min_seconds` / `max_seconds`).
- `enabled_layers` must be a non-empty list; `[4]` alone degrades silently to `[1]` via `build_layers_for_source` (Layer 4 not implemented).

Streamlit re-reads `config/sources.json` on every render, so you can swap the file between test runs and just press F5 — no need to restart Streamlit.

### 3. Run the app

```bash
cd /home/ubuntu/repos/news-scraper
.venv/bin/python /home/ubuntu/test-plans/fixture_server.py &
.venv/bin/python -m streamlit run app.py --server.headless true --server.port 8501 --browser.gatherUsageStats false &
```

Streamlit serves the Dashboard at `http://localhost:8501/` (NOT `/dashboard` — that 404s because st.navigation's default page is mounted at `/`).

## JS pagination (Iter 7+) — click_next and infinite_scroll

For `click_next` / `infinite_scroll` sources, the engine routes to a persistent headless Chromium page (see `scraper/runner.run_browser_source`). The `url_params` recipe above does **not** apply — those sources need a real HTTP server (no `file://`) serving HTML that the browser can evaluate JS from.

The simplest recipe is to serve the existing deterministic fixtures verbatim:

```python
# /home/ubuntu/test-plans/fixture_server_js.py
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
FIXTURES = "/home/ubuntu/repos/news-scraper/tests/fixtures"
class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw): super().__init__(*a, directory=FIXTURES, **kw)
    def log_message(self, *a, **k): pass
os.chdir(FIXTURES)
ThreadingHTTPServer(("127.0.0.1", 8766), H).serve_forever()
```

Then seed `config/sources.json` with `enabled_layers=[3]` and `pagination_type` set appropriately:

```json
{
  "name": "ClickNextSite",
  "pagination_type": "click_next",
  "url_template": "http://127.0.0.1:8766/click_next.html",
  "selectors": {"container": "article.news-card", "title": "h3 a", "link": "h3 a", "date": "time", "next_button": "#next"},
  "enabled_layers": [3], "scrolls_per_page": 1,
  "avg_page_per_month": 10, "sleep": {"min": 0.0, "max": 0.0}, "max_retries": 0, "enabled": true
}
```

End Page comes from `max(end_page)` across all selected sources (see `ui/pages/main_dashboard.py`) — so per-source rows share a single `/N` denominator. When writing test assertions, pin the **items count**, not the `/N` — the latter is source-selection-dependent.

## Discriminating-UA fixture server (proving fallback cascades)

When testing code that picks between two code paths based on an outbound header (e.g. Layer 1 uses desktop-Chrome UA, Layer 2 uses mobile iOS Safari UA), a fixture that 403s one UA and 200s the other is the cleanest adversarial proof of the cascade. Pair it with a control run where only the "blocked" layer is enabled to prove the fixture truly blocks.

```python
# /home/ubuntu/test-plans/fixture_server_ua.py
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FIXTURE = Path("/home/ubuntu/repos/news-scraper/tests/fixtures/portalx_listing.html").read_text()
LOG = Path("/home/ubuntu/test-plans/fixture_server_ua.log")
LOG.write_text("")  # truncate on start

DISCRIMINATOR = "iPhone"  # substring to match the "preferred" UA

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        ua = self.headers.get("User-Agent", "")
        with LOG.open("a") as f: f.write(f"{self.path}\t{ua}\n")
        body = FIXTURE.encode() if DISCRIMINATOR in ua else b"403 blocked"
        code = 200 if DISCRIMINATOR in ua else 403
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a, **k): pass

ThreadingHTTPServer(("127.0.0.1", 8767), H).serve_forever()
```

**Always run BOTH of these:**
1. **Primary (cascade enabled):** source with `enabled_layers=[blocked_layer, preferred_layer]` → verify success + preferred layer in stats.
2. **Control (cascade disabled):** same source, `enabled_layers=[blocked_layer]` only → verify failure.

The control is what proves the fixture genuinely blocks. Without it, you can't tell if the primary-run success came from the cascade or from accidentally-permissive fixture behavior. **Also inspect the server log after each run** — it's the smoking gun for "was the blocked layer actually attempted" (primary must show the blocked UA too, not just the preferred one).

Streamlit re-reads `config/sources.json` on every render, so `cp control.json config/sources.json && F5` swaps between runs without restarting the app.

## Temporary progress_panel patch for engine-only stats

Some iterations add instrumentation (counts, per-layer aggregates, timing stats) to `RunStats` or the `Event` stream that has no permanent UI surface — the Settings form and Results tables don't know about it yet. To visually verify this instrumentation end-to-end, apply a small temporary patch to `ui/components/progress_panel.py` and revert before reporting.

The shape of the patch for aggregating a new `PageFetched.<field>` into a caption:

1. Add a new field to `ProgressSnapshot`:
   ```python
   per_layer_used: dict[int, int] = field(default_factory=dict)
   ```
2. In `_apply_events`, on each `PageFetched`:
   ```python
   if ev.layer_used is not None:
       snap.per_layer_used[ev.layer_used] = snap.per_layer_used.get(ev.layer_used, 0) + 1
   ```
3. In `_render_panel`, right after the completion banner:
   ```python
   if snap.per_layer_used:
       usage = ", ".join(f"L{n}={snap.per_layer_used[n]}" for n in sorted(snap.per_layer_used))
       st.caption(f"Layer usage: {usage}")
   else:
       st.caption("Layer usage: (none)")
   ```

Before writing the test report, always revert: `git checkout -- ui/components/progress_panel.py`. The working tree must be clean before posting results.

The pattern generalizes to any dict/counter stat on `Event` or `RunStats`. Don't ship this patch — if the user wants a permanent UI surface, that's a separate iteration.

## Screen recording

```python
computer(action="record_start")
# ... drive the UI ...
computer(action="record_annotate", type="setup", description="...")
computer(action="record_annotate", type="test_start", test="It should ...")
# after each assertion:
computer(action="record_annotate", type="assertion", test="It should ...", test_result="passed", assertion="...")
computer(action="record_stop", title="...", summary="...")
```

Always `wmctrl -r :ACTIVE: -b add,maximized_vert,maximized_horz` before starting the recording — a half-covered browser recording is useless. Use `google-chrome http://localhost:8501` to open a new tab in the already-running Chrome (do NOT try to `kill` / relaunch Chrome).

## Interacting with `st.data_editor`

`st.data_editor` cells are **not** normal `<input>` elements you can click and type into directly. The cell value is committed only after you press `Enter` or click out of the cell. The reliable sequence is:

1. **Double-click** the cell — a single click only selects it, double-click enters edit mode.
2. `ctrl+a` — select all current text in the cell.
3. Type the new value — this replaces the selected text.
4. Press `Enter` — commits the new value to the underlying frame.

For the Category column, which is a `SelectboxColumn`, double-click opens the dropdown, then click the desired option (no typing).

## Per-grouping pivot is a pinned snapshot

The pivot below each grouping's data_editor is NOT live — editing a row's category does not re-pivot the numbers. The user must click **Update Pivot** for the pivot to refresh against the current editor state. Test assertion for the pin: edit a row, verify pivot counts are **unchanged**; click Update Pivot, verify counts **now match** the edited frame. Both halves must hold; an auto-refresh pivot or a dead button would break differently.

The pivot is always reindexed on the full category list (`rules`), so zero-match categories still appear as `0`-columns. This is a regression trap — if a future change uses `pandas.pivot` without explicit reindex, zero-match categories silently disappear. Always test with at least one rule that matches zero articles to pin this down.

## Fragment-driven Results auto-population

After a scrape finishes, the Results tabs (Iter 5+) must populate without a manual click. This is driven by `ui/components/progress_panel.py::_live_fragment` calling `st.rerun(scope="app")` exactly once when it observes the `finished` transition. Assertion: click **Start Scraping**, wait for completion banner, verify Results tabs show rows without touching the page. A regression here looks like `No scrape results yet. Click Start Scraping above...` lingering after the banner appears.

## Devin Secrets Needed

None. Everything in this skill runs against localhost fixtures.
