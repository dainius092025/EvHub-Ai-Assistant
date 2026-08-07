# PIPPLINE.md

## Running the pipeline

```bash
# Full pipeline on default PDF (PDF/vc.pdf)
python main.py

# Full pipeline on a specific PDF
python main.py PDF/ha.pdf

# Run individual stages in isolation
python detector.py          # reads PDF/ha.pdf by default
python extractor.py         # reads PDF/ha.pdf by default
python classifier.py
python contents_parser.py
python section_classifier.py
python validator.py
```

## Architecture

This is a **6-stage linear PDF extraction pipeline** for Nissan EV workshop manuals. Each stage writes its output to disk before the next stage reads it. Stages do not call each other — `main.py` wires the sequence.

```
PDF
 │
 ▼
detector.py        → raw/shared_profile.json          (document identity: SHA-256 ID, section code, year, model, outline availability)
 │
 ▼
extractor.py       → raw/N_M.json + raw/images/       (raw content batches via Docling; 10 pages per batch; resumes on partial runs)
 │
 ▼
classifier.py      → output/{SECTION}_classified.json (noise removal + element/table/image tagging; merges all raw batches)
 │
 ▼
contents_parser.py → raw/section_map.json             (PDF outline → nested section tree with Y-position boundaries)
 │
 ▼
section_classifier.py → output/{SECTION}_sectioned.json  (assign every element to a section; build merged_text per section)
 │
 ▼
validator.py       → output/validation_report_classified.json  (advisory — failure logs warnings but does NOT stop pipeline)
```

### Extraction libraries

- **Docling** (`docling==2.91.0`) — primary text and table extraction. Returns bounding boxes where **bbox[1] = Y from bottom of page** (PDF coordinate origin: bottom-left). Higher `bbox[1]` = higher on page.
- **PyMuPDF / fitz** (`PyMuPDF==1.27.2.3`) — image extraction, footer/header region scanning, visual TOC fallback parsing. Uses **Y from top** (origin: top-left). Lower value = higher on page.
- **pypdf** (`pypdf==6.10.2`) — PDF outline (bookmark) extraction for `contents_parser.py`.

### Coordinate system invariant — critical

These two conventions coexist in the codebase and must never be mixed:

| Source | bbox[1] meaning | Higher value = |
|--------|----------------|----------------|
| Docling (`b.t`, `extractor._docling_bbox()`) | Y from bottom | Higher on page |
| pymupdf `page.get_text()` / `page.get_imageinfo()` | Y from top | Lower on page |

In `section_classifier.py`:
- `_to_pdf_y(bbox)` returns `float(bbox[1])` directly — **no conversion needed** because Docling already produces Y-from-bottom.
- `_build_merged_text()` sorts by `-bbox[1]` (negated) so ascending sort = top-to-bottom reading order.
- `_find_best_section()` compares element Y against section `top_y_start`/`top_y_end` which also come from PDF bookmarks (Y-from-bottom via pypdf `/Top` field).

### Section assignment rules (`section_classifier.py`)

`MIN_ASSIGNMENT_LEVEL = 2` — L0 and L1 nodes in the section tree are structural containers (e.g., "Table of Contents", top-level chapter). Text elements are only assigned to L2+ nodes.

`_find_best_section()` uses **closest-heading-above**:
1. Filter to sections that spatially cover the element (`_belongs_to()`).
2. Among sections that **start on the element's page**, pick the one with the **smallest `top_y_start` ≥ element's Y** — i.e., the heading immediately above.
3. If no section starts on that page (interior page), fall back to the deepest covering section.

Tables and images that land on pages with only L0/L1 sections use a `flat_all` fallback (includes all levels). TOC tables are never assigned to sections — they go to `unassigned`.

### Output contracts

`output/{SECTION}_classified.json` — validated against `classified_batch.schema.json` (draft-07, schema_version "2.0"). Required top-level fields: `schema_version`, `schema_type`, `document_id`, `section_code`, `batch`, `text_elements`, `tables`, `images`.

`raw/shared_profile.json` — validated against `shared_profile.schema.json` (draft 2020-12). **Locked contract — do not modify the schema.**

### Single source of truth: `config.py`

All Nissan-specific patterns, thresholds, and DTC detection rules live in `config.py`. No magic strings or hardcoded values elsewhere. Key constants:

- `BATCH_SIZE = 10` — pages per Docling extraction batch
- `FOOTER_HEIGHT_PCT = 0.04` / `HEADER_HEIGHT_PCT = 0.04` — region scanned for page references
- `NISSAN_PAGE_REF_PATTERN` — regex matching `HA-34`, `EVB-5`, etc.
- `NISSAN_SECTION_NAMES` — maps section codes (HA, EVB, VC, …) to human-readable names
- `SAFETY_TRIGGERS` — keyword sets for HIGH_VOLTAGE / CAUTION / WARNING safety levels
- `DTC_SIGNALS` / `DTC_CONFIDENCE_THRESHOLD` — weighted scoring for DTC page detection (used by `splitter.py`, Phase 3, not yet wired into `main.py`)

### Document identity

`document_id` = SHA-256 of the PDF file bytes. Stable across re-runs. Joins `ev-pdf-cars-adapter` output with the DTC adapter.

Section code is detected from Nissan footer page references (`HA-34` → code `HA`) found by scanning the first 10 pages via pymupdf.

### Structural authority

When the PDF has internal bookmarks (`primary_source = "internal_outline"`), `contents_parser.py` uses them for the section map with Y-position boundaries.

When there are no bookmarks, `_visual_toc_fallback()` parses dot-leader TOC lines from the first 5 pages. This produces level=1 sections only with placeholder Y=742.0, meaning `MIN_ASSIGNMENT_LEVEL=2` will exclude all of them from text assignment — run on the full PDF, not a page excerpt.

