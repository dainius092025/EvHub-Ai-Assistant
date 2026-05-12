# index_builder.py

Scans a PDF for DTC index tables and returns a code → pages map.
Called by `extractor.py` as Step 1 of the extraction pipeline.

---

## What this file does

- Scans all pages for a `"DTC Index"` heading block with an `INFOID:` marker
- Locates the index table on that page (or the next page)
- Extracts DTC codes, their titles, and their page-ref hyperlinks
- Handles multi-page index tables by following consecutive pages
- Returns `{ "P0A0D": {"pages": [88], "page_refs": ["EVB-88"], "title": "HV SYSTEM INTERLOCK ERROR"}, … }`

---

## Public functions

### `build_index(pdf_path)`
Main entry point. Scans all pages and returns the DTC code map.

One code can map to multiple pages (e.g. a code appearing in multiple TYPE sections).
`pages` and `page_refs` are parallel lists — `page_refs[i]` corresponds to `pages[i]`
and may be `None` if no hyperlink was found for that entry.

### `find_dtc_heading_y(page)`
Returns the bottom y-coordinate of the `"DTC Index"` heading block, or `None`.
The heading must have `"DTC Index"` as its first line AND contain `"INFOID:"` —
prevents false matches on body text that happens to say "DTC Index".

### `find_index_table(page, heading_y)`
Finds the index table below the heading. Prefers a table whose header row contains
a `"Reference"` column — distinguishes the real index from a Pattern A/B/C/D
carry-over table that may appear above the index on the same page.

### `detect_format(header_row)`
Returns `"A"` (dedicated DTC column) or `"B"` (codes embedded in brackets like `[U1000]`).

### `extract_codes_with_y(page, fmt, min_y)`
Extracts `(code, y_position, title)` tuples from a page.
`min_y` excludes codes above the index table top — prevents picking up carry-over codes.
Title = all words to the right of the code on the same Y level, stopping at `×`, digits,
page refs, or another code.

### `match_codes_to_links(codes_with_y, links)`
Row/block-aware link matching. Groups codes into visual rows (±4 pt Y tolerance),
groups rows into blocks (>40 pt gap = new block), matches each row to the nearest
link within the same block. Codes with no matching link are warned and skipped —
better to drop than to assign a wrong page.

---

## Private functions / constants

| Name | Purpose |
|---|---|
| `_quiet()` | Context manager: suppresses PyMuPDF's `"Consider pymupdf_layout"` advisory during `find_tables()` |
| `_ROW_Y_TOL = 4` | pt — codes within this Y band share the same visual row |
| `_LINK_Y_TOL = 20` | pt — a link's midY must be within this of a row's Y to match |
| `_BLOCK_GAP = 40` | pt — Y gap larger than this between rows starts a new block |

---

## Notes

- Page numbers are 1-based throughout (consistent with `type_detector.py` and `extractor.py`)
- Multi-page index: the loop advances page by page until it finds no more codes or hits another `"DTC Index"` heading
- `seen_pages` prevents processing the same index page twice when multiple index tables exist in one PDF
