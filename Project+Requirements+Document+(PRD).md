**Project Requirements Document (PRD)**

**Project Name:** News Scraper & Categorization WebApp

**Platform:** Streamlit (Frontend) + Python (Backend)

**Version:** 1.4 (Final with User Flows)

**1\. Project Overview**

A Streamlit-based web application designed to perform parallel, fault-tolerant (anti-fail), and human-like web scraping of various news portals. The scraped data is automatically classified into multiple custom groupings (e.g., Indonesian GDP Sectors, Expenditure Categories) based on text-based token rules. The application heavily prioritizes scalability; users can add/edit news sources and categorization rules entirely via the User Interface (UI) without modifying the source code.

**2\. Tech Stack Requirements**

- **Frontend & UI:** streamlit
- **Backend & Concurrency:** Python with asyncio or Background Threads (ThreadPoolExecutor) to ensure the Streamlit UI does not block/freeze and progress bars update smoothly in real-time.
- **Scraping Engine (Multi-Layer Strategy):**
  - **Layer 1:** httpx / requests + BeautifulSoup4 (Fast path for static HTML).
  - **Layer 2:** API Requests (Direct endpoint hits via reverse-engineered intercepts).
  - **Layer 3:** Playwright (For Single Page Applications (SPA), JS-rendered DOMs, clicking pagination buttons, and scroll simulations).
  - **Layer 4:** Playwright + playwright-stealth + Proxy rotation (For bypassing strict anti-bot protections).
- **Data Processing:** pandas (For dataframe manipulation, filtering, and 2-way pivot table generation).
- **Date Parsing:** dateparser (Capable of parsing various date text formats, specifically Indonesian locales like "5 menit lalu", "Kemarin", "12 Jan 2026").
- **Storage Configuration:** Local filesystem using JSON or YAML to persist all configuration states, categorizer rules, and scraper definitions.

**3\. UI/UX Specifications**

**3.1. Main Page (Scraping Dashboard)**

This page serves as the operational hub for data extraction.

- **A. Time Range Filter Component**
  - **Inputs:** Dropdowns for Start Month, Start Year, End Month, End Year.
  - **Quick Selectors (Buttons):** "This Month", "Last Month", "This Quarter", "Last Quarter", "Last 6 Months", "This Year". Clicking these automatically populates the manual inputs.
  - **Function:** Dynamically filters scraping targets.
  - **Early Stopping Logic (CRITICAL):** If the scraper parses a news date that is _older_ than the selected time range, scraping for that specific source MUST **automatically halt** to save resources, even if the target "End Page" has not been reached.
- **B. Target Scraper & Page Range Component**
  - Displays a list of configured news sources with Checkboxes.
  - Inputs for Start Page and End Page per source.
  - **Auto-calculate:** The system automatically pre-fills the End Page based on the calculation: (Selected Time Range in Months) \* (Configured Avg Pages/Month).
- **C. Action Buttons & Progress**
  - **"Start Scraping"** button.
  - **Progress Bars:** 1 Overall Progress Bar AND Individual Progress Bars for each active source. These MUST run asynchronously.
- **D. Scraping Results Area (Data Viewer & Editor)**
  - Displays tabs or stacked vertical tables:
    - **News Table by \[Grouping 1\] (Editable):**
      - Columns: Category, News Title, Link, Date.
      - Users can edit the 'Category' cell directly via st.data_editor.
      - **Multi-category Logic:** If a single news article matches multiple categories within this grouping, the article MUST be **duplicated into multiple distinct rows** (1 row per matching category).
    - **Monthly Pivot Table \[Grouping 1\]:**
      - 2-way pivot table.
      - Static Column (Leftmost): Category. **Absolute Requirement:** ALL categories defined in the configuration MUST be displayed in a constant order, even if no scraped news falls into them (render with empty/null values).
      - Dynamic Columns (Right): Month-Year (e.g., Jan-26, Feb-26). Populated with concatenated text/links of Titles, Links, Dates.
      - "Update Pivot Table" button to refresh the pivot view based on any manual edits made in the editable table above.
    - **News Table by \[Grouping 2\] (Editable)** -> Same structure as Grouping 1.
    - **Monthly Pivot Table \[Grouping 2\]** -> Same structure as Grouping 1.
    - _... \[Grouping N, etc.\]_
    - **Raw Data Table:** A read-only dataframe of all successfully scraped data. Columns: Title, Link, Date, Source, Page.

**3.2. Settings Page (Configuration)**

- **A. Categorization Configuration Tab**
  - **Overall Exclude Tokens:** Text/Tag input. Any news containing these tokens is globally marked as "Unclassified" / discarded.
  - **Grouping Management (Categorizer Tables):**
    - Editable tables (Columns: Category, Include_tokens, Exclude_tokens).
    - Supports CSV/Excel upload to Create/Read/Update/Delete (CRUD) rules.
- **B. Scraper Configuration Tab**
  - Parameters: Source Name, URL Template, Selectors (Title/Link/Date), Avg Pages/Month.
  - **Pagination Type Select:** Dropdown with options:
    - url_params (Modifies URL parameters, e.g., ?page=2).
    - infinite_scroll (Simulates constant downward scrolling).
    - click_next (Simulates clicking a "Next Page" or pagination number button).
  - **Dynamic Inputs based on Pagination Type:**
    - IF infinite_scroll: Show input for Scrolls per Page (How many scroll actions equate to 1 logical page).
    - IF click_next: Show input for Next Button Selector (CSS/XPath for the next button).
  - **Tooling:** **"Test Selector"** button.
  - **Resilience Settings:**
    - Min Sleep (sec) & Max Sleep (sec): Generates a random, human-like delay between actions.
    - Max Retries.
    - Allowed Scraping Layers (Select 1-4).

**4\. System & Logic Specifications**

**4.1. Advanced Scraper Engine & Pagination Handling**

- **4-Layer Fallback Strategy:** Engine attempts Layer 1. If it fails or is blocked, escalate to Layer 2, then Layer 3, etc., up to the configured Allowed Scraping Layers.
- **Pagination Handling Mechanism:**
  - **url_params:** Replaces the {page} placeholder in the URL template and executes the request (Supports Layers 1-4).
  - **infinite_scroll:** Forces Layer 3/4 (Playwright). The engine simulates physical scroll-down actions iteratively to replicate "page" increments.
  - **click_next:** Forces Layer 3/4 (Playwright). Loads the base URL, extracts data, simulates .click() on the Next Button Selector, waits for network idle, and loops until the time range limit or End Page is reached.
- **Early Stopping Execution:** Evaluated at every page iteration / scroll / click. This requires dateparser to process scraped dates _on-the-fly_ concurrently with the scraping loop.

**4.2. Date Parsing & Standardization**

- Utilize dateparser with locales=\['id', 'en'\].
- Standardized output format for the dataframe: DD-MM-YYYY.

**4.3. Categorization Engine Core Logic**

- Convert the scraped title to lowercase and strip all punctuation.
- Evaluate against Include_tokens and Exclude_tokens (comma-separated lists in the config).
- If an article matches >1 Category in a specific Grouping, perform a deep copy of the article dictionary/row for each matched Category.

**4.4. Concurrency & Performance**

- **Parallel Across Sources:** Scraping tasks for different news portals run concurrently via asyncio.gather or ThreadPoolExecutor on a background thread. UI remains unblocked.
- **Sequential Within Source:** Page navigation (URL swaps, scrolls, or clicks) _within_ a single portal must execute sequentially with time.sleep(random.uniform(min_sleep, max_sleep)) between actions to prevent IP bans.

**5\. Data Structure Example (JSON Config Draft)**

JSON

{

"sources": \[

{

"name": "Portal News X",

"pagination_type": "url_params",

"url_template": "<https://portalx.com/indeks?page={page}>",

"selectors": {

"container": ".article-item",

"title": "h2 > a",

"link": "h2 > a",

"date": ".date-time"

},

"avg_page_per_month": 45,

"sleep": {"min": 1.5, "max": 4.0},

"max_retries": 3,

"enabled_layers": \[1, 3\]

},

{

"name": "Portal News Y",

"pagination_type": "click_next",

"url_template": "<https://portaly.com/berita>",

"selectors": {

"container": ".list-item",

"title": ".title",

"link": "a.read-more",

"date": ".publish-date",

"next_button": ".pagination > button.next"

},

"avg_page_per_month": 30,

"sleep": {"min": 2.0, "max": 5.0},

"max_retries": 2,

"enabled_layers": \[3, 4\]

}

\]

}

**6\. User Flows & Expected Behavior**

_This section defines UI states and interactions to guide the architectural setup._

**Use Case 1: Daily Scraping & Data Manipulation**

- **Navigate:** User opens the app on the "Main Page".
- **Time Filter:** User clicks the "This Month" quick selector. The system auto-fills the Start/End month and year dropdowns.
- **Select Target:** User checks target sources (e.g., Kompas, Detik). The system auto-calculates and fills the End Page input (e.g., 30 pages) based on config averages.
- **Execute:** User clicks "Start Scraping".
- **Monitor:** Overall and individual progress bars render. The UI remains fully interactive (no freezing).
- **Review:** Dataframes populate upon completion. User views the "News by GDP Sector" editable table.
- **Manipulate:** User spots a misclassified row, clicks the 'Category' cell, and corrects the value via st.data_editor.
- **Sync Pivot:** User clicks "Update Pivot Table". The system reads the modified dataframe and re-renders the 2-way Pivot Table below it.

**Use Case 2: Adding a New Scraper Source**

- **Navigate:** Go to "Settings Page" > "Scraper Configuration" tab.
- **Basic Info:** Click "Add New Scraper". Enter Name (e.g., "Tribun News").
- **Setup Logic:** Enter URL Template, select Pagination Type (e.g., url_params), set Min/Max Sleep.
- **Setup Selectors:** Input CSS selectors for the article container, title, link, and date.
- **Testing (Crucial Step):** User pastes a single specific URL into a "Test URL" input field and clicks **"Test Selector"**.
- **Validate:** The backend runs a single-page scrape and outputs raw JSON to the UI. If the title/link/date look correct, the user proceeds.
- **Save:** Click "Save Configuration". The new source instantly appears as a checkbox on the Main Page.

**Use Case 3: Scraping Error Handling (Troubleshooting)**

- **Trigger:** During a live scrape, Target Website X changes its DOM structure, causing selectors to fail.
- **System Response:** Engine utilizes the anti-fail logic. It retries up to Max Retries. If it fails across all permitted Layers, it gracefully aborts that specific source/page **without crashing the entire application**.
- **UI Feedback:** App renders an st.warning or st.error (e.g., _"Failed scraping Portal X on page 5. Could not find title element. Selectors may have changed or IP blocked."_).
- **Action:** User navigates to "Settings Page" > "Scraper Configuration".
- **Investigate:** User selects "Portal X", inputs the failed URL, and clicks "Test Selector".
- **Fix:** Output is empty/error. User inspects the website in their browser, finds the new CSS selector, and updates the form in the WebApp.
- **Retest & Save:** User tests again. Upon success, clicks "Save" and returns to the Main Page to resume.

**Use Case 4: Managing Categorization Rules**

- **Navigate:** Go to "Settings Page" > "Categorization Configuration" tab.
- **Global Rules:** User adds the word "sponsor" to Overall Exclude Tokens to globally ignore sponsored content.
- **Add New Grouping:**
  - User clicks "Add New Grouping".
  - Prompts for a name (e.g., "News Sentiment").
  - User uploads a CSV (containing: Category, Include_tokens, Exclude_tokens).
  - System parses the CSV and generates a new editable table in the UI.
- **Edit Existing Grouping:**
  - User views the existing "GDP Sector" table.
  - User adds a row manually via st.data_editor or modifies Include_tokens for better accuracy.
- **Save:** User clicks "Save Category Rules". Changes apply to the next scraping classification cycle.