# pdf_profile.py

Quick PDF pre-check before extraction starts.
Called by both `pipeline.py` and `extractor.py`.

---

## What this file does

- Reads PDF document metadata (title, author, dates, encryption status)
- Samples the first 5 pages to determine if the PDF has a text layer
- Samples the first 5 pages for internal hyperlinks
- Runs merged-manual detection on digital PDFs (structural signals only)
- Returns a `(metadata, pdf_profile)` tuple

---

## Public functions

### `profile_pdf(pdf_path)`
Returns `(metadata, pdf_profile)`.

**`metadata` fields:**

| Field | Source |
|---|---|
| `title` | PDF header |
| `author` | PDF header |
| `subject` | PDF header |
| `keywords` | PDF header |
| `creator` | Software that created the PDF |
| `producer` | Software that produced the PDF |
| `format` | PDF version e.g. `"PDF 1.4"` |
| `creation_date` | PDF header |
| `modification_date` | PDF header |
| `encryption` | String describing encryption type, or `null` if not encrypted |

**`pdf_profile` fields:**

| Field | Value |
|---|---|
| `is_digital` | `True` if any sampled page has >50 chars of text |
| `needs_ocr` | `True` when `is_digital` is False |
| `has_links` | `True` if any internal links found in sample |
| `has_internal_links` | Same as `has_links` (kind == 4) |
| `link_count_sample` | Count of internal links across sampled pages (stripped from output by `extractor.py`) |
| `pdf_type` | `"digital"`, `"merged"`, or `"scanned"` |
| `merged_detection` | Result of `detect_merged()` — see below; `null` for scanned PDFs |

---

### `detect_merged(pdf)`
Analyses structural signals on an already-open `fitz.Document` to decide if the PDF is a merged manual (multiple workshop sections stitched into one file). Called internally by `profile_pdf()` on digital PDFs only.

**Signals checked:**

| Signal | Score |
|---|---|
| Page labels with 2+ distinct section-code prefixes (e.g. `EVB-`, `EVC-`, `TM-`) | +3 |
| TOC with 5+ top-level sections | +2 |
| TOC with 2–4 top-level sections | +1 (weak) |

**Scoring → verdict:**

| Score | `is_merged` | `confidence` |
|---|---|---|
| ≥ 3 | `true` | `"high"` |
| ≥ 2 | `true` | `"medium"` |
| ≥ 1 | `false` | `"low"` |
| 0 | `false` | `"high"` |

**Returns** `{ is_merged, confidence, evidence[], notes[] }` — saved as `pdf_profile.merged_detection` in the JSON output.

---

## Notes

- Sample size is 5 pages — enough for a quick decision without scanning the whole file
- A hybrid PDF (mostly digital, few scanned pages) is classified as `"digital"` — per-page OCR fallback handles isolated scanned pages
- `link_count_sample` is an internal diagnostic field; `extractor.py` strips it before including `pdf_profile` in the output JSON
- `pdf_type` drives the pipeline decision: `"scanned"` → stub written; `"merged"` → flagged in output (pipeline does not yet split merged PDFs)
- Page label signal is the most reliable: if `EVB-` and `EVC-` both appear as label prefixes, the PDF is almost certainly merged
