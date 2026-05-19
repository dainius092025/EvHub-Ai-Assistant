# content_extractor.py

Core PDF text and table extraction engine.
Provides the two main public functions called by `extractor.py` for each DTC record,
plus a set of private utilities that support heading detection, table repair, image handling,
and section boundary tracking.

---

## What this file does

Drives a page-by-page extraction loop for a single DTC record.
For each page it:
- detects known section headings and splits the page into zones
- extracts and cleans text from each zone
- extracts tables with multi-pass quality assessment and repair
- saves images and records their metadata
- collects unknown-heading warnings for developer visibility

Returns structured data consumed by `extractor.py`.

---

## Public functions

### `extract_content(pdf, start_page, codes, output_dir, ...)`
Main entry point. Accepts an already-open `fitz.Document` — the caller opens the PDF once and passes it in for every DTC group, avoiding repeated file I/O. Processes pages starting at `start_page` while the page header still belongs to the DTC codes. Runs a section state machine: when a known heading is found, the current section closes and a new one opens. Returns sections, tables (per section), images, page refs, unknown-heading warnings, and image extraction warnings.

Image extraction is resilient — a single corrupt or unsupported image does not crash the run. Failures are caught per-image, logged to the terminal as `[WARN]`, and collected in `image_warnings[]` for inclusion in the record's `extraction.warnings` field.

**Stops when:**
- Page header no longer contains the record's DTC codes
- Section code prefix changes (e.g. EVB → EVC) — cross-section boundary in merged PDFs
- Manual TYPE changes (TYPE 1 → TYPE 2) — triggers a split record in the caller

### `extract_tables_from_rect(page, rect)`
Extracts all tables overlapping `rect` by at least 50%. Multi-pass pipeline:
1. PyMuPDF `find_tables()` detection
2. Outer column recovery (columns missing due to absent vertical border lines)
3. Bbox repair via drawn horizontal rules or word-level reconstruction
4. Quality flag assignment and confidence scoring
5. `cleaned_rows` derivation (layout newlines joined, hyphens repaired)

Returns list of `{rows, cleaned_rows, extraction}` dicts. Never silently discards a table — flags instead.

### `clean_text(raw, section_code)`
Cleans raw zone text:
- Strips OEM content IDs (INFOID:…)
- Strips single-letter sidebar tab characters
- Repairs soft hyphens (`diag-\nnosis` → `diagnosis`)
- Drops noise lines (page refs, revision lines, model names, DTC title headers)
- Drops standalone section code sidebars (e.g. bare `EVB`)
- Collapses excess blank lines

### `read_page_ref(page)`
Reads the printed footer page label (e.g. `EVB-88`) from the bottom 12% of the page.

### `page_belongs_to_codes(page, codes)`
Checks whether the page header (first 300 chars) contains any of the given DTC codes.
Used to decide when a record's page span ends.

---

## Private functions

| Function | Purpose |
|---|---|
| `_find_heading_y(page, heading)` | Returns `(y_top, y_bottom)` of a known heading on the page; used to split zones |
| `_find_structural_headings(page)` | Scans for bold/short lines NOT in `HEADING_LOOKUP`; produces unknown-heading warnings |
| `_get_line_extent(page, table_bbox)` | Finds the horizontal extent of drawn horizontal rules overlapping a table |
| `_drawn_table_rect(page, table_bbox)` | Derives true table bounds from drawn border rectangles (fallback for bad PyMuPDF bboxes) |
| `_row_y_ranges(table)` | Derives per-row y-ranges from a table's cell bounding boxes |
| `_bbox_rebuild_table(page, repair_rect)` | Reconstructs table rows via word-level geometry clustering; used for outer column recovery |
| `_dedup_merged_cells(rows)` | Collapses repeated consecutive values per column (merged cell artefact from bbox rebuild) |
| `_clean_zone_text(page, rect, section_code)` | Thin wrapper: `page.get_text()` + `clean_text()` |
| `_extract_oem_content_id(page, rect)` | Extracts INFOID identifier from a rect |
| `_get_table_bboxes_in_zone(page, rect)` | Returns table bboxes overlapping a rect |
| `_finalize_section(section)` | Converts internal section builder dict to final output dict |
| `_find_image_caption(page, xref)` | Finds short alphanumeric identifier below an image |

---

## Module-level constants

| Name | Purpose |
|---|---|
| `_PAGE_REF_RE` | Matches printed page labels: `EVB-88`, `TM-44`, etc. |
| `_SIDEBAR_VAL_RE` | Matches sidebar navigation tab values (single/short uppercase strings) |
| `_STRUCTURAL_HEADING_EXCLUDES` | List of compiled regexes that filter false-positive heading candidates |

---

## Confidence model (`extract_tables_from_rect`)

Starts at `"high"`. Lowest signal wins.

| Signal | Effect |
|---|---|
| `blob_row_detected`, `single_row_table`, `single_column_table` | → `"low"` |
| `bbox_reconstruction_used`, `outer_column_recovered`, `bbox_clipped_by_drawings`, `wide_bbox_uncorrected` | → `"medium"` |

---

## External dependencies

| Import | Used for |
|---|---|
| `patterns.INFOID_RE` | Strip OEM content IDs from text |
| `patterns.SIDEBAR_RE` | Strip sidebar tab characters |
| `patterns.IMAGE_ID_RE` | Match image caption identifiers |
| `text_parser.KNOWN_HEADINGS` | Scan for known section headings per page |
| `text_parser.HEADING_LOOKUP` | Skip known headings in unknown-heading detection |
| `text_parser.normalize_heading` | Case/whitespace-normalised heading comparison |
| `text_parser.is_noise` | Drop noise lines from extracted text |

---

## Risky areas

- **`extract_tables_from_rect`** — multi-pass quality flag pipeline; confidence model depends on exact flag name strings. Do not rename flags.
- **`_bbox_rebuild_table`** — geometric clustering with empirically tuned thresholds (`ROW_TOL`, `X0_TOL`, `WORD_GAP`). Do not adjust without re-running on the full EVB PDF.
- **`extract_content`** — section state machine with page boundary and TYPE boundary logic. Behavioral changes here affect all records. Image extraction is wrapped per-image so one bad image cannot abort the loop.

---

## Flagged for future review

- **`_get_table_bboxes_in_zone`** — defined but not called anywhere in this file or in `extractor.py`. Possibly dead code from an earlier approach. Verify before removing.
- **`_clean_cell` (nested function)** — defined inside `extract_tables_from_rect`. Moving it to module level would make it independently testable with no behavior change.
- **`_dedup_merged_cells`** — defined here but called from `extractor.py`, not from this file. Logically belongs closer to where it's used; could be moved in a future refactor.
- **Table-entry dict duplication** — `{page, page_ref, rows, cleaned_rows, extraction}` is constructed identically in 3 places inside `extract_content`. A helper `_make_table_entry(page_num, ref, td)` would reduce duplication safely.
