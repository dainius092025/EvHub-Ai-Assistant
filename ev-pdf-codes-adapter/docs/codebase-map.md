# Codebase Map — ev-pdf-codes-adapter

High-level overview of every source file in `src/` and `scripts/`.
Each entry links to the per-file summary in `docs/files/`.
Updated after each file is reviewed or refactored.

**Guides:**
- [Adding a new manufacturer](adding-a-manufacturer.md) — checklist for onboarding a PDF from an untested make
- [Known limitations](known-limitations.md) — source data constraints discovered during testing (not pipeline bugs)

---

## Pipeline entry point

| File | Summary | Doc |
|---|---|---|
| `pipeline.py` | CLI entry point. Scans `manuals/` for PDFs, calls `extract_records`, writes JSON output. Output folder and filename use a canonical stem derived from vehicle metadata: `{make}_{model}_{year}_{section}` (e.g. `nissan_leaf_2013_evb`). Falls back to PDF filename stem if metadata unavailable. Default output is importer-oriented (slim); `--full` adds human-readable helper fields. | [pipeline.md](files/pipeline.md) |

---

## Extraction layer

| File | Summary | Doc |
|---|---|---|
| `extractor.py` | Orchestrates DTC record extraction for a single PDF. Segments pages by DTC codes, calls `extract_content`, assembles the final JSON record structure including tables, sections, images, and table_groups. | [extractor.md](files/extractor.md) |
| `content_extractor.py` | Core PDF text and table extraction engine. Page loop, section state machine, table extraction with multi-pass repair and quality flags, image saving, unknown-heading detection. | [content_extractor.md](files/content_extractor.md) |

---

## Support modules

| File | Summary | Doc |
|---|---|---|
| `text_parser.py` | `KNOWN_HEADINGS` registry, `HEADING_LOOKUP` dict, `normalize_heading()`, `is_noise()`. Controls which section headings are recognised and which lines are discarded as page noise. | [text_parser.md](files/text_parser.md) |
| `patterns.py` | Compiled regex constants shared across the pipeline: `CODE_RE`, `REF_RE`, `SIDEBAR_RE`, `INFOID_RE`, `IMAGE_ID_RE`. | [patterns.md](files/patterns.md) |
| `type_detector.py` | Detects `TYPE N` manual variant boundaries in a PDF. Produces a `{pdf_page: "TYPE N"}` map used by `extractor.py` to split multi-type records. | [type_detector.md](files/type_detector.md) |
| `pdf_profile.py` | Profiles a PDF before extraction: detects scanned vs digital, samples link density, and runs merged-manual detection (structural signals — page label prefixes, TOC depth). Sets `pdf_type` to `"digital"`, `"merged"`, or `"scanned"`. Returns `merged_detection` in the profile dict. Called by `pipeline.py` to skip scanned PDFs early. | [pdf_profile.md](files/pdf_profile.md) |
| `vehicle_info.py` | Extracts vehicle metadata (make, model, year, variant, revision date) from PDF footer, foreword, document properties, or lookup file. | [vehicle_info.md](files/vehicle_info.md) |
| `index_builder.py` | Scans PDF for DTC index tables, extracts codes → pages + titles map. Called by `extractor.py` as Step 1. | [index_builder.md](files/index_builder.md) |

---

## Debug scripts (`scripts/`)

| File | Summary | Doc |
|---|---|---|
| `scripts/debug_table.py` | Manual debug tool: renders a single PDF page to the terminal — tables, drawn lines, sidebar zone. Not part of the production pipeline. | [debug_table.md](files/debug_table.md) |

---

## Key data contracts

- **`raw_rows`** — source of truth: true PyMuPDF extraction output, no reconstruction applied.
- **`cleaned_rows`** — formatting-only version of `raw_rows`: layout newlines joined, hyphens repaired. No inferred values.
- **`reconstructed_rows`** — carry-forward fill + merged-cell dedup applied. Present only when reconstruction actually changed data. Always accompanied by `reconstruction` metadata block.
- **`cleaned_text`** — noise-filtered section text (INFOID stripped, hyphens repaired, noise lines removed).
- **`raw_text`** — unprocessed zone text from PyMuPDF. Full output only (`--full`).

---

## Output modes (`pipeline.py`)

| Mode | Command | Content |
|---|---|---|
| Default (importer) | `python src/pipeline.py` | `raw_rows`, `reconstructed_rows`, `reconstruction`, `cleaned_text`, all metadata |
| Full (human-readable) | `python src/pipeline.py --full` | All of the above + `raw_text`, `raw_table_text`, `cleaned_table_text`, `ocr_used` |
