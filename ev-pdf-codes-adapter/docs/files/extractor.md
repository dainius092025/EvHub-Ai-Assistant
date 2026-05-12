# extractor.py

Orchestrates DTC record extraction for a single PDF.
Sits between `pipeline.py` (caller) and `content_extractor.py` (page-level engine).

---

## What this file does

- Profiles the PDF and builds the DTC index
- Detects manual TYPE boundaries (pre-pass)
- Loops over DTC code groups by start page
- Calls `extract_content` per page segment; handles TYPE boundary splits
- Applies table post-processing: blob strip, carry-forward fill, merged-cell dedup
- Detects cross-page table continuations → `table_groups`
- Assigns stable IDs to records, sections, tables, images
- Assembles and returns the final document-level JSON object

---

## Public functions

### `extract_records(pdf_path, output_dir)`
Main function called by `pipeline.py`. Returns one document-level dict for the PDF.

**Flow:**
1. `compute_document_id` — SHA256 of PDF bytes
2. `profile_pdf` — metadata + pdf_type
3. `extract_vehicle_info` — make/model/year
4. `build_index` — DTC code → pages + titles map
5. `detect_manual_types` — `{pdf_page: "TYPE N" | None}` pre-pass
6. Per DTC group: `extract_content` → TYPE segment loop → table post-processing → `_merge_continued_tables` → finalize
7. Returns document envelope with `records[]`

**TYPE segment loop:** if `extract_content` stops at a TYPE boundary, the same
code group is re-extracted starting from the next page under the new `manual_type`.
No pages are dropped.

---

## Private functions

| Function | Purpose |
|---|---|
| `_common_title_prefix(titles)` | Longest common word-level prefix of a list of titles; used to build multi-code record titles |
| `_normalize_title(codes, code_titles)` | Builds compact record title: single code → `"P0A0D HV SYSTEM INTERLOCK ERROR"`; multi-code → `"P3031-P303C CELL CONT"` |
| `_headers_match(row_a, row_b)` | True when two header rows represent the same column layout — exact match or prefix match (handles Nissan continuation pages dropping a trailing column) |
| `_merge_continued_tables(tables, notes, record_num)` | Detects cross-page continuations in the same section with matching headers; returns `(table_groups, absorbed_ids)`; does NOT modify raw tables |
| `_is_blob_row(row)` | True when row 0 is a PyMuPDF blob: long multi-line first cell, all other cells empty; secondary structural check gating blob strip |
| `_is_subheader_row(row, known_codes)` | True when every non-empty cell could be a header label (no DTC codes, no plain integers) |
| `_row_has_dtc_codes(row, known_codes)` | True when any cell is a known DTC code — such rows are always data, never headers |
| `_detect_header_rows(raw_rows, known_codes)` | Returns 1 or 2 — how many leading rows form the header; detects gap-fill and parent-category two-row headers |
| `_merge_header_rows(row0, row1)` | Combines two header rows into single column labels (`"Module" + "Connector"` → `"Module Connector"`) |
| `_fill_carry_forward(raw_rows, header_count)` | Propagates non-empty cell values downward through data rows; makes every row self-contained |
| `_dedup_merged_cells(rows)` | Collapses repeated consecutive values per column — merged-cell artefact from bbox reconstruction; imported from `content_extractor.py` |
| `_render_raw_table_text(raw_rows)` | Pipe-delimited render of raw_rows; no cleanup; full output only |
| `_render_cleaned_table_text(cleaned_rows)` | Pipe-delimited render of cleaned_rows; full output only |
| `_make_record_id(document_id, manual_type, start_pdf_page)` | SHA256-based 16-char deterministic record ID |

---

## Table post-processing pipeline

Runs on each table before `_merge_continued_tables`. Uses private `_`-prefixed keys
to carry intermediate state through the finalize loop.

```
extracted          ← deep copy of raw rows (true snapshot — never modified)
rows_for_recon     ← extracted[1:] if blob stripped, else extracted
header_count       ← _detect_header_rows(rows_for_recon)
filled             ← _fill_carry_forward(rows_for_recon, header_count)
deduped            ← _dedup_merged_cells(filled)
norm               ← ["blob_row_stripped"?] + ["carry_forward_fill"?] + ["merged_cell_dedup"?]
```

**Output fields set per table:**
- `raw_rows` — `extracted` (true PyMuPDF output, never modified)
- `reconstructed_rows` — `deduped` (only present when `norm` is non-empty)
- `reconstruction.normalization_applied` — ordered list of operations run
- `extraction.quality_flags` — extended with `norm` entries + `reconstructed_rows_present`
- `extraction.confidence` — `"high"` → `"medium"` when any reconstruction ran
- `extraction.header_rows_hint` — raw heuristic count (importer should verify)
- `extraction.partial` — True when row after headers also passes subheader test (3+ level header)

**Reconstruction order is fixed:** `blob_row_stripped` always first (if present), then `carry_forward_fill`, then `merged_cell_dedup`.

---

## Key constraints

- `raw_rows` is immutable — carry-forward and dedup only touch `rows_for_recon` (the copy)
- `blob_row_stripped` only fires when **both** `blob_row_detected` quality flag is set **and** `_is_blob_row` structural check passes
- `partial` check uses `rows_for_recon[header_count]`, not `extracted[header_count]` — indices align with the rows carry-forward and dedup were computed on
- `_merge_continued_tables` receives the post-reconstruction `rows` (via `tbl["rows"] = deduped`) so table_groups also contain complete rows

---

## External dependencies

| Import | Used for |
|---|---|
| `content_extractor.extract_content` | Page-level extraction for one DTC record |
| `content_extractor._dedup_merged_cells` | Merged-cell dedup (defined there, used here) |
| `pdf_profile.profile_pdf` | PDF metadata + type detection |
| `vehicle_info.extract_vehicle_info` | Make/model/year from PDF |
| `index_builder.build_index` | DTC code → page + title map |
| `type_detector.detect_manual_types` | Manual TYPE boundary pre-pass |
| `shared.document_id.compute_document_id` | Stable document hash |
