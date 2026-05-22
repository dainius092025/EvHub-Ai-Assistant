# EvHub Crawler — Core

A modular, config-driven Python crawler framework that extracts structured article data from websites. The crawler is intentionally site-agnostic: site-specific behavior is provided by small connector modules and a JSON selector configuration.

Example site key used throughout this README: `example-news` (a made-up placeholder).

## Overview

This project provides:

- A lightweight `BaseCrawler` for HTTP fetching, parsing with BeautifulSoup, rate limiting, and URL normalization.
- A folder-per-site connector model: each site adds a small crawler module and a `config.json` with CSS selectors and index pages.
- An `adapter` layer that converts raw extraction results into a consistent JSON schema for downstream consumers.
- A simple CLI `main.py` to run a site crawler and persist results as JSON.
- Unit tests to verify parsing and adapter behavior.

## Key Concepts

- Config-driven scraping: each site provides `config.json` keys such as `base_url`, `index_pages`, `article_selector`, `title_selector`, `content_selector`, `image_selector`, and `category_selector`. This keeps site logic small and declarative.
- Adapter normalization: crawled articles are converted to a stable schema with keys like `title`, `content`, `summary`, `images`, `categories`, `tags`, `fault_codes`, `part_numbers`, `comments`, `published_date`, and `source`.
- Extraction safeguards: the crawler includes heuristics for selecting real image URLs (prefer `data-src`/`srcset`), deduplicating by normalized title, basic language heuristics, and targeted regexes to extract fault codes and part numbers.

## Project Structure

- `crawler/` — base classes and utilities (HTTP session, parsing helpers, URL normalization).
- `sites/<site_key>/` — per-site connector (crawler, `config.json`, optional `description.txt` and `data.json`).
- `adapters/` — normalization functions (e.g., `adapt_article`).
- `main.py` — CLI to run a site crawler and write adapted JSON to `sites/<site_key>/data.json`.
- `requirements.txt` — Python dependencies.
- `tests/` — unit tests using `pytest`.

## Adapter Schema (summary)

The adapter returns a dictionary with the following common fields:

- `title` — article title string
- `content` — extracted article text
- `summary` — short summary (first ~200 characters)
- `images` — list of normalized image URLs
- `categories` — list of article categories (filtered and normalized)
- `tags` — list of tags
- `fault_codes` — extracted fault codes (OBD/manufacturer style)
- `part_numbers` — extracted part numbers (digits or mixed-format)
- `comments` — extracted comments with `author`, `text`, and `date`
- `published_date` — publication date string
- `source` — canonical article URL

## How to Add a New Site

1. Create `sites/<your-site-key>/`.
2. Add `config.json` with `base_url`, `index_pages`, and selectors.
3. Add a small site crawler module if the site needs custom parsing; otherwise the base crawler + config can often suffice.
4. Optionally add `description.txt` and an initial `data.json` for sample data.
5. Run the crawler via the CLI (see below).

## Running the Crawler (example)

From the project folder that contains `ev-site-crawler/`:

```bash
cd ev-site-crawler
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run the crawler for a configured site key (replace `example-news` with your site key)
python main.py --site example-news --max-articles 60 --delay 1.0 --log-level INFO
```

The CLI writes the adapted list of articles to `sites/<site_key>/data.json`.

## Testing & Development

- Unit tests live under `tests/`. Run them with:

```bash
python -m pytest -q
```

- Use the adapter unit tests to verify schema changes when you tweak extraction rules.
