# `app/services/scraper.py` Architecture

## Purpose

`CareerSiteScraper` is the scraping layer for company career data. It has two responsibilities:

1. Fetch and normalize career-site content into `ScrapedPage` objects.
2. Convert certain structured scrape outputs into `ExtractedJob` records when a company-specific parser exists.

The file combines a generic HTML crawler with company-specific structured scrapers for Robinhood and Rippling.

## Main Types

### `ScrapedPage`

A small dataclass used as the normalized scrape artifact:

- `url`: source page URL
- `title`: page title or fallback URL
- `text`: cleaned text payload used downstream

### `CareerSiteScraper`

Stateful scraper service that owns:

- request timeout configuration
- page discovery limit
- a shared `requests.Session`
- a custom user agent for all outbound requests

## High-Level Flow

### 1. Entry point: `scrape_company(company_url)`

This is the primary scrape orchestrator.

Flow:

1. Normalize the incoming URL.
2. Route to a company-specific scraper when supported.
3. Otherwise discover likely career pages with the generic crawler.
4. Scrape each discovered page into cleaned text.
5. Return a list of `ScrapedPage` objects.

Routing behavior:

- Robinhood career domains use `_scrape_robinhood_open_roles()`.
- Rippling career URLs use `_scrape_rippling_open_roles()`.
- All other URLs use generic discovery plus HTML scraping.

### 2. Text aggregation: `build_text_dump(company_url, pages)`

Builds a single plain-text document from scraped pages. This output is the common downstream handoff format for extraction or storage.

### 3. Structured extraction: `extract_company_jobs(company_url, scraped_text)`

This is a second-stage parser for company-specific text dumps.

Current behavior:

- Robinhood text dumps can be parsed back into `ExtractedJob` records.
- All other companies currently return `None`.

## Generic Scraping Path

The generic path is designed for career sites that expose jobs in ordinary HTML pages.

### URL discovery

`_discover_career_urls()` performs bounded discovery:

- seeds a queue with common career paths plus the original company URL
- fetches pages breadth-first
- marks a page as career-related if the URL or page content matches career heuristics
- extracts same-host candidate links from anchors containing career keywords
- stops once `max_pages` discovered pages are collected

If no career page is found, it falls back to the original company URL.

### Page scraping

`_scrape_page()`:

- fetches HTML with `_get()`
- removes `script`, `style`, and `noscript` tags
- extracts visible text via BeautifulSoup
- normalizes blank lines
- returns a `ScrapedPage`

### Career heuristics

Generic discovery relies on:

- `CAREER_KEYWORDS` for URL and anchor matching
- `COMMON_CAREER_PATHS` as discovery seeds
- `_looks_like_career_url()` for keyword-based URL checks
- `_looks_like_career_page()` for shallow HTML content checks
- `_extract_candidate_links()` for same-domain career-oriented links

## Robinhood-Specific Path

Robinhood bypasses HTML crawling and uses Greenhouse's board API directly.

### Detection

`_is_robinhood_careers_url()` checks for Robinhood career-host URLs.

### Data flow

1. `_scrape_robinhood_open_roles()` calls `_fetch_robinhood_jobs()`.
2. `_fetch_robinhood_jobs()` loads JSON from Greenhouse via `_get_json()`.
3. `_filter_robinhood_jobs()` keeps only engineering jobs with US locations.
4. `_extract_robinhood_us_locations()` expands and cleans location sources.
5. `_is_us_location()` classifies locations using explicit remote labels, country text, and US state codes.
6. `_build_robinhood_jobs_text_dump()` renders the filtered records into a deterministic text dump.
7. The result is returned as a single `ScrapedPage`.

### Extraction support

`_extract_robinhood_jobs_from_text_dump()` parses the Robinhood text dump back into `ExtractedJob` models using regex.

This makes Robinhood the only company in this file with a full structured scrape-to-extract pipeline.

## Rippling-Specific Path

Rippling also bypasses generic crawling, but its data source is page-embedded Next.js JSON rather than a public JSON API.

### Detection

`_is_rippling_careers_url()` checks for Rippling career URLs.

### Data flow

1. `_scrape_rippling_open_roles()` derives `/careers/open-roles`.
2. `_get()` fetches the HTML page.
3. `_extract_rippling_next_data()` parses the `__NEXT_DATA__` script payload.
4. `_filter_rippling_jobs()` keeps engineering jobs with US locations that include a city.
5. `_build_rippling_jobs_text_dump()` renders the filtered roles into a single text dump.
6. The result is returned as one `ScrapedPage`.

Unlike Robinhood, Rippling currently has no corresponding `ExtractedJob` parser in `extract_company_jobs()`.

## Network Layer

Two private helpers isolate HTTP access:

- `_get(url)` for HTML responses only
- `_get_json(url)` for JSON APIs

Shared characteristics:

- use the shared `requests.Session`
- apply the configured timeout
- raise on HTTP errors
- log failures and return `None` instead of raising upstream

This keeps the scraper resilient and makes higher-level methods operate in a best-effort mode.

## Data and Dependency Boundaries

External dependencies:

- `requests` for HTTP
- `BeautifulSoup` for HTML parsing and text extraction
- `re` for content matching and structured text parsing
- `urllib.parse` for URL normalization and host checks
- `app.models.ExtractedJob` as the downstream structured output model

Internal file-level constants:

- `CAREER_KEYWORDS`
- `COMMON_CAREER_PATHS`
- `US_STATE_CODES`

These constants drive discovery heuristics and US-location filtering.

## Error Handling and Logging

The architecture is intentionally non-fatal:

- network and parse failures are logged
- most failures return `None` or an empty list
- Robinhood can fall back to the generic scraper if its structured scrape finds no jobs
- generic scraping skips pages with missing or very short text

This design favors continuing partial progress over failing the entire scrape.

## Current Extension Pattern

To add a new company-specific scraper, the current pattern is:

1. Add a URL detector such as `_is_example_careers_url()`.
2. Add a structured scraper returning `ScrapedPage`.
3. Optionally add a text-dump-to-`ExtractedJob` parser.
4. Wire both into `scrape_company()` and `extract_company_jobs()`.

That means this file acts as both:

- the generic scraping engine
- the registry for special-case company scrapers

## Current Limitations

- Company-specific logic is centralized in one file, so specialization will keep growing this module.
- Only Robinhood supports deterministic `ExtractedJob` reconstruction.
- Generic scraping depends on shallow keyword heuristics and visible HTML text, so JavaScript-heavy job boards may still be missed.
- The scraper is synchronous and serial across requests/pages.
