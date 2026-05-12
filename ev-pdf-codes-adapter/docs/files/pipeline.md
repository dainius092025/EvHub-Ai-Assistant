# pipeline.py

CLI entry point for the extraction pipeline.
Scans `manuals/` for PDFs (or accepts a single PDF argument), runs extraction,
and writes JSON output to `data/<stem>/<stem>.json`.

---

## What this file does

- Parses CLI arguments (`pdf`, `--force`, `--full`)
- Resolves the list of PDFs to process
- Profiles each PDF (`pdf_profile.py`) and skips scanned PDFs early
- Calls `extract_records()` for each digital PDF
- Writes output as importer-oriented JSON (default) or full human-readable JSON (`--full`)
- Writes stub JSON for scanned or empty PDFs so they appear in output with a clear reason
- Prints a processing report to terminal and saves it to `data/processing_report.json`
- Appends to a persistent `data/run_history.json` (never overwrites, only grows)

---

## CLI usage

```
python src/pipeline.py                         # all PDFs in manuals/, skip existing
python src/pipeline.py manuals/EVB.pdf         # single PDF, skip if already done
python src/pipeline.py --force                 # all PDFs, overwrite existing output
python src/pipeline.py manuals/EVB.pdf --force # single PDF, force reprocess
python src/pipeline.py manuals/EVB.pdf --full  # single PDF, human-readable output
```

---

## Functions

### `main()`
Full pipeline loop. Resolves PDF list → profiles each PDF → calls `extract_records` →
writes JSON output → prints report → appends to run history.

**Skip logic:** if `data/<stem>/<stem>.json` already exists and `--force` is not set,
the PDF is skipped entirely. Use `--force` to reprocess.

**Atomic write:** output is written to `<stem>.json.tmp` first, then renamed to
`<stem>.json`. If the process crashes mid-write, the `.json` file is never created
and the next run retries cleanly.

**Error isolation:** each PDF is wrapped in `try/except`. One bad PDF never kills
the rest of the run. The error is logged to the report and the JSON file is not written.

### `_apply_slim(result)`
Strips human-readable helper fields from the extraction result for default (importer) output.

**Removed fields:**
- `sections[].raw_text` — raw uncleaned zone text
- `tables[].raw_table_text` — rendered string of raw_rows
- `tables[].cleaned_table_text` — pipe-formatted cleaned view
- `tables[].extraction.ocr_used` — always False for digital PDFs

**Kept fields (importer needs all of these):**
- `sections[].cleaned_text`
- `tables[].raw_rows`
- `tables[].reconstructed_rows` (when present)
- `tables[].reconstruction` (when present)
- `tables[].extraction`

---

## Stub JSON

Written when a PDF cannot be fully extracted. Two cases:

| Case | Reason written |
|---|---|
| Scanned PDF | `"scanned PDF — OCR not yet supported"` |
| No DTC codes found | `"no DTC codes found"` |

Stub always includes `document_id`, `source_file`, `metadata`, `pdf_profile`,
and `processing.extraction_completed: false`. Records list is empty.

---

## Output files (per PDF)

| File | Contents |
|---|---|
| `data/<stem>/<stem>.json` | Main extraction output (importer or full) |
| `data/<stem>/images/` | Extracted wiring diagram images (PNG) |
| `data/processing_report.json` | Last run summary |
| `data/run_history.json` | All runs appended, never overwritten |

---

## External dependencies

| Import | Used for |
|---|---|
| `extractor.extract_records` | Core extraction for a single PDF |
| `pdf_profile.profile_pdf` | PDF type detection (digital vs scanned) |
| `shared.document_id.compute_document_id` | Stable document hash for tracking |
