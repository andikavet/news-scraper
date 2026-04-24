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

### 3. Run the app

```bash
cd /home/ubuntu/repos/news-scraper
.venv/bin/python /home/ubuntu/test-plans/fixture_server.py &
.venv/bin/python -m streamlit run app.py --server.headless true --server.port 8501 --browser.gatherUsageStats false &
```

Streamlit serves the Dashboard at `http://localhost:8501/` (NOT `/dashboard` — that 404s because st.navigation's default page is mounted at `/`).

## Reference: exact widget keys & texts

- Time range radio: key `tr_main_preset`, options `This Month | Last Month | Year to Date | This Year | Custom`
- Source-row checkbox: key `ss_main_<sourcename>_checked`
- Source Start/End inputs: keys `ss_main_<sourcename>_start` / `ss_main_<sourcename>_end`
- Start Scraping: key `start_scrape_btn` (primary button, disabled while run in progress)
- Stop: key `progress_panel_stop` (only rendered while `handle.is_running()`)
- Completion banner: `Run complete. N items in range.` (✅)
- Cancelled banner: `Run cancelled. Collected N items before stopping.` (⏹️)
- Overall progress text format: `Overall: Running · X/Y sources done (Z%)` / `Overall: Completed (100%)` / `Overall: Cancelled (Z%)`
- Per-source bar format: `**<name>** — D/T pages · I items in range`
- Results tabs: `Raw Data` + one per grouping (Section D)
- Grouping-tab editor caption format (Iter 5+): `N row(s) across M unique article(s) · K rule(s) in this grouping`
- Update Pivot button (Iter 6+): key `update_pivot__<grouping name>`, located to the right of the Source × Category pivot

## Reference: interacting with `st.data_editor` cells

`st.data_editor` renders cells as a canvas, not HTML — normal selector-based click/type does not work. To edit a cell:

1. **Double-click** the cell at its screen coordinate. A textarea appears in the DOM with the cell's current value selected.
2. **`ctrl+a`** then **type the new value** (replaces the selection). Do NOT rely on typing alone clearing the cell — it will append to the selected text if the selection was lost.
3. **Press `Enter`** to commit. Streamlit fires a partial rerun with the edited frame.

Because the cell content is rendered on a canvas, automated DOM inspection can't read the new value back. Verify the edit visually (screenshot) and via downstream side effects — e.g. clicking an `Update Pivot` style button and asserting the pivot counts change.

### Pinned-snapshot pattern (used by Iter 6 pivot)

When a UI has an `X` widget whose output is recomputed only on an explicit button click (not on every upstream edit), test by:

- Take a screenshot of `X` before the edit — note its values.
- Make the upstream edit.
- **Before clicking the button**, take another screenshot — `X` should still show the pre-edit values. This proves no auto-refresh.
- Click the button, take a third screenshot — `X` now reflects the edit.

All three screenshots must be captured for the test to be decisive. If you only screenshot the final state, a broken auto-refresh implementation is indistinguishable from a correct pinned-snapshot one.

## Key assertions to exercise

1. **Default state:** `End` auto-computes to `avg_page_per_month × months_span` (e.g. This Month × avg=3 → End=3)
2. **Primary run:** banner reads `Run complete. N items in range.` with the exact expected N for your fixture (2 sources × 3 pages × 3 articles = 18 for the 3-article fixture)
3. **Non-blocking UI (the hard one):** kick off a 10-page run, then click a radio / expand an expander / click a checkbox mid-run. The interaction should respond <1s while progress bars continue advancing. A blocking UI could not produce this frame.
4. **Cancellation:** click Stop at ~30% progress; within one fragment tick the banner switches to `Run cancelled. Collected N items before stopping.` with `N > 0`.
5. **Categorization explosion (Iter 5+):** design at least one article to match ≥2 rules in the same grouping; assert the editor caption row count > unique article count.
6. **Full-category reindex (Iter 6+):** include at least one rule in the grouping that matches zero articles in the fixture; assert it still appears as a `0`-column in the pivot.

## Gotchas

- A 1s/page fixture isn't slow enough to catch mid-run state reliably on a fast machine. Use 2–3s for progress/cancellation tests.
- Use `end_page=10` (not 3) for the non-blocking test so the run lasts long enough to click through widgets.
- For categorization/pivot tests, drop the sleep entirely — you want a fast complete run so you can immediately interact with results.
- The results section stays empty on an empty-results run until something else triggers a full-page rerun — this was fixed in PR #11 via a `st.rerun(scope="app")` in the progress fragment. If testing shows Results empty after completion, check that `ui/components/progress_panel.py` still has the `K_FRAGMENT_SAW_FINISHED` sentinel logic.
- `data_editor` canvas cells require double-click to edit (single-click just selects); the editing textarea appears at the bottom of the DOM and is NOT inside the canvas element.
