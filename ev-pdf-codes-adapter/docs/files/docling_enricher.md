# docling_enricher.py

Experimental post-processor — enriches pipeline JSON with Docling table extraction.
**Not used in production. Crashed on EVB.pdf.**

---

## What it does

Reads a pipeline output JSON, runs Docling's `DocumentConverter` on each DTC record's
pages, and writes the Docling-extracted tables back into the JSON (atomic write).

Optimisations vs earlier probes:
- One `DocumentConverter` instance shared across all pages (model loads once)
- OCR disabled — text PDFs don't need it
- Only DTC pages processed, not the full PDF

---

## Usage

```
python src/docling_enricher.py EVB
python src/docling_enricher.py EVB --force
```

---

## Status

**Crashed on EVB.pdf** with `RapidOCR / std::bad_alloc` (memory allocation failure).
Decision: keep PyMuPDF as the production engine. Docling stays experimental only.

See memory file `project_docling_experiment.md` for the full incident record.
