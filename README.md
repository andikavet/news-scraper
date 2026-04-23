# News Scraper & Categorization WebApp

A Streamlit-based web application for **parallel, fault-tolerant, human-like** web scraping of
news portals, with automatic multi-grouping classification via configurable token rules.

All scraping sources and categorization rules are managed **through the UI** — no code changes
required to add a new portal or grouping.

## Status

Early iteration scaffold. See [project-requirements-document.md](./docs/PRD.md) for the full
specification (to be committed). Built step-by-step; the current iteration focus is recorded in
`CHANGELOG` entries on the PRs.

## Tech Stack

- **UI:** Streamlit
- **Concurrency:** `asyncio` running inside a background `ThreadPoolExecutor` worker so the
  Streamlit UI never blocks.
- **Scraping (4-layer fallback):**
  1. `httpx` + `BeautifulSoup4` (static HTML)
  2. Direct API endpoint hits (reverse-engineered)
  3. `Playwright` (SPA / JS-rendered DOM / scroll / click-next)
  4. `Playwright` + `playwright-stealth` + proxy rotation (anti-bot bypass)
- **Data:** `pandas`
- **Dates:** `dateparser` with `locales=['id', 'en']`, standardised to `DD-MM-YYYY`
- **Config:** JSON + YAML on local filesystem, validated with `pydantic`

## Project Structure

```
news-scraper/
├── app.py              # Streamlit entry — routes to pages only
├── config/             # Persistent JSON/YAML config + typed loaders
├── ui/                 # Streamlit pages + reusable components
├── scraper/            # Engine, per-source runner, 4 layers, pagination
├── categorizer/        # Token-rule classifier + pivot builder
├── utils/              # Logging, text utils, atomic IO, async bridge
└── tests/              # pytest
```

Hard rules:

- `ui/` never imports from `scraper/layers/*` directly — only via `scraper.engine`.
- `scraper/` has **zero** Streamlit imports (keeps it testable headless).
- `config/store.py` is the only module that touches config JSON/YAML files.

## Quick Start

```bash
# 1. Install Python deps (Python 3.11+ recommended)
pip install -r requirements.txt

# 2. Install Playwright browser (needed for Layer 3 & 4)
playwright install chromium

# 3. Run the app
streamlit run app.py
```

The app opens at `http://localhost:8501`.

## Development

```bash
# Tests
pytest

# Lint + format
ruff check .
ruff format .

# Type check
mypy .
```

## License

TBD.
