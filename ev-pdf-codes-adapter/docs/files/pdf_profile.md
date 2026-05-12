# pdf_profile.py

Quick PDF pre-check before extraction starts.
Called by both `pipeline.py` and `extractor.py`.

---

## What this file does

- Reads PDF document metadata (title, author, dates, encryption status)
- Samples the first 5 pages to determine if the PDF has a text layer
- Samples the first 5 pages for internal hyperlinks
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
| `encrypted` | `True` if password-protected |

**`pdf_profile` fields:**

| Field | Value |
|---|---|
| `is_digital` | `True` if any sampled page has >50 chars of text |
| `needs_ocr` | `True` when `is_digital` is False |
| `has_links` | `True` if any internal links found in sample |
| `has_internal_links` | Same as `has_links` (kind == 4) |
| `link_count_sample` | Count of internal links across sampled pages (stripped from output by `extractor.py`) |
| `pdf_type` | `"digital"` or `"scanned"` |

---

## Notes

- Sample size is 5 pages — enough for a quick decision without scanning the whole file
- A hybrid PDF (mostly digital, few scanned pages) is classified as `"digital"` — per-page OCR fallback handles isolated scanned pages
- `link_count_sample` is an internal diagnostic field; `extractor.py` strips it before including `pdf_profile` in the output JSON
- `pdf_type` drives the pipeline decision: `"scanned"` → stub JSON written, extraction skipped
