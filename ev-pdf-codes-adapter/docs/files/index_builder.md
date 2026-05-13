# index_builder.py

Scans a PDF for DTC index tables and returns a code → pages map.
Called by `extractor.py` as Step 1 of the extraction pipeline.

---

## What this file does

- Scans all pages looking for a heading that matches `DTC_INDEX_HEADINGS` (multi-manufacturer frozenset in `patterns.py`)
- Builds a footer scan map (`page_ref → pdf_page`) once at startup for use as a fallback
- Locates and validates the index table on the matching page (or the next page)
- Extracts DTC codes, their titles, and their destination pages
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
Returns the bottom y-coordinate of the DTC index heading block, or `None`.
Matches any heading in `DTC_INDEX_HEADINGS` (case-insensitive, first line of block).

### `find_index_table(page, heading_y)`
Finds the index table below the heading. Prefers a table whose header row contains
a `"Reference"` column — distinguishes the real index from carry-over tables above it.

If no `"Reference"` column is found, applies a **rejection check** before falling back:
if the table header contains words like `"description"`, `"action"`, `"malfunction"`, or
`"factor"`, the table is rejected and `None` is returned. This prevents self-diagnosis
description pages (e.g. AV-159) from being mistaken for a DTC index when they share
a heading like `"Self-diagnosis results"`.

Falls back to `candidates[0]` only when the header is garbled or missing but not disqualified.

### `detect_format(header_row)`
Returns `"A"` (dedicated DTC column) or `"B"` (codes embedded in brackets like `[U1000]`).

### `extract_codes_with_y(page, fmt, min_y)`
Extracts `(code, y_position, title)` tuples from a page.
`min_y` excludes codes above the index table top — prevents picking up carry-over codes.
Title = all words to the right of the code on the same Y level, stopping at `×`, digits,
page refs, or another code.

### `match_codes_to_links(codes_with_y, links, page_ref_map)`
Row/block-aware link matching. Groups codes into visual rows (±4 pt Y tolerance),
groups rows into blocks (>40 pt gap = new block), matches each row to the nearest
link within the same block. Codes with no matching link are warned and skipped —
better to drop than to assign a wrong page.

`page_ref_map` is accepted for API consistency but is not used in Format B matching —
Format B rows embed no reference text, so there is nothing to look up without a link.

---

## Private functions / constants

| Name | Purpose |
|---|---|
| `_quiet()` | Context manager: suppresses PyMuPDF's `"Consider pymupdf_layout"` advisory during `find_tables()` |
| `_build_page_ref_map(pdf)` | Scans every page footer once at startup. Returns `{"EVB-88": 288, …}` (1-based). Used as fallback when hyperlinks are absent. |
| `_ref_col_idx(header_row)` | Returns the column index of the Reference column. Falls back to last column. |
| `_read_format_a_table(page, table, links, page_ref_map)` | Table-based extraction for Format A index pages. Reads rows directly, handles merged reference cells via carry-forward. Links filtered to the reference column x-zone (≥60% table width) and consumed in Y order. Falls back to footer scan map when no hyperlink is available for a reference group. |
| `_ROW_Y_TOL = 4` | pt — codes within this Y band share the same visual row |
| `_LINK_Y_TOL = 20` | pt — a link's midY must be within this of a row's Y to match |
| `_BLOCK_GAP = 40` | pt — Y gap larger than this between rows starts a new block |

---

## Notes

- Page numbers are 1-based throughout (consistent with `type_detector.py` and `extractor.py`)
- Multi-page index: the loop advances page by page until it finds no more codes or hits another DTC index heading
- `seen_pages` prevents processing the same index page twice when multiple index tables exist in one PDF
- The footer scan map (`_build_page_ref_map`) adds ~0.1s on a 1500-page PDF (text clip only) and is built once regardless of which path is taken
