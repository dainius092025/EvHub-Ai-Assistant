# Codebase Map — ev-pdf-codes-adapter

High-level overview of every source file in `src/`.
Each entry links to the per-file summary in `docs/files/`.
Updated after each file is reviewed or refactored.

---

## Pipeline entry point

| File | Summary |
|---|---|
| `pipeline.py` | CLI entry point. Scans `manuals/` for PDFs, calls `extract_records`, writes JSON output. Default output is importer-oriented (slim); `--full` adds human-readable helper fields. | [pipeline.md](files/pipeline.md) |

---

## Extraction layer

| File | Summary | Doc |
|---|---|---|
| `extractor.py` | Orchestrates DTC record extraction for a single PDF. Segments pages by DTC codes, calls `extract_content`, assembles the final JSON record structure including tables, sections, images, and table_groups. | — |
| `content_extractor.py` | Core PDF text and table extraction engine. Page loop, section state machine, table extraction with multi-pass repair and quality flags, image saving, unknown-heading detection. | [content_extractor.md](files/content_extractor.md) |

---

## Support modules

| File | Summary | Doc |
|---|---|---|
| `text_parser.py` | `KNOWN_HEADINGS` registry, `HEADING_LOOKUP` dict, `normalize_heading()`, `is_noise()`. Controls which section headings are recognised and which lines are discarded as page noise. | — |
| `patterns.py` | Compiled regex constants shared across the pipeline: `INFOID_RE`, `SIDEBAR_RE`, `IMAGE_ID_RE`. | — |
| `type_detector.py` | Detects `TYPE N` manual variant boundaries in a PDF. Produces a `{pdf_page: "TYPE N"}` map used by `extractor.py` to split multi-type records. | — |
| `pdf_profile.py` | Profiles a PDF before extraction: detects scanned vs digital, counts pages, samples link density. Called by `pipeline.py` to skip scanned PDFs early. | — |
| `vehicle_info.py` | Extracts vehicle metadata (make, model, year) from PDF document properties or cover page text. | — |

---

## Utility / debug scripts

| File | Summary |
|---|---|
| `debug_table.py` | Manual debug tool: renders a single table from a PDF page to the terminal. Not part of the production pipeline. |
| `diag.py` | Diagnostic script for inspecting extraction output. Not part of the production pipeline. |
| `index_builder.py` | Builds a search index from extracted JSON records. Run separately from the pipeline. |
| `docling_enricher.py` | Experimental Docling-based enrichment. Crashed on EVB.pdf (RapidOCR / std::bad_alloc). Not used in production. |
| `script_for_meta.py` | One-off script for metadata extraction. Not part of the production pipeline. |

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
