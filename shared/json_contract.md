# JSON Output Contract — EV PDF Codes Adapter

This document defines the shape of every JSON file produced by this adapter.
It is split into two parts:

1. **Shared profile** — identical structure in every adapter (codes adapter, cars adapter, any future adapter). The importer reads this first.
2. **Adapter-specific fields** — unique to this adapter. The cars adapter will have different fields here.

Both adapters join on `document_id` — so the importer can combine a DTC record
and a procedure record from the same PDF using one stable key.

---

## Shared dependency — `shared/` folder

Both adapters use the same shared folder:

```
shared/
  document_id.py       ← SHA-256 of PDF file bytes → document_id
  vehicle_lookup.json  ← maps model names to make (e.g. "LEAF" → "Nissan")
```

**Rule:** both adapters must use `shared/document_id.py` to compute `document_id`.
Never invent a different formula. If both adapters process the same PDF,
they must produce the same `document_id` — that is how the importer links them.

---

## Full contract

```jsonc
{

  // ═══════════════════════════════════════════════════════════════
  //  SHARED PROFILE
  //  Written by BOTH adapters. Identical structure every time.
  //  The importer reads these fields before touching adapter-specific data.
  // ═══════════════════════════════════════════════════════════════

  // MUST HAVE — importer checks this first.
  // If the schema changes in a breaking way, this version changes.
  // Importer rejects files it cannot read.
  "schema_version": "1.0",

  // MUST HAVE — identifies what kind of document this is.
  // When a third adapter is added it will also use this same type.
  "schema_type": "shared_document_profile",

  // MUST HAVE — stable unique ID for this PDF across all systems.
  // Computed by shared/document_id.py as SHA-256 of the PDF file bytes.
  // If the same PDF is processed twice, the ID is identical.
  // Importer uses this to deduplicate on re-runs and to join records
  // from different adapters that processed the same PDF.
  "document_id": "a1b2c3d4e5f6...",

  // MUST HAVE — which file this came from.
  // Importer uses this to report errors, trace bad records,
  // and display source provenance in the UI.
  "source_file": "EVB.pdf",

  // NICE TO HAVE — raw PDF metadata baked into the file by the publisher.
  // Not needed for extraction today but useful for:
  //   - auditing (when was this manual created or revised?)
  //   - detecting duplicate manuals with different filenames
  //   - future: auto-filling vehicle info when extraction fails
  "metadata": {
    "title":             null,
    "author":            null,
    "subject":           null,
    "keywords":          null,
    "creator":           "Nissan Motor Co.",
    "producer":          "Acrobat Distiller",
    "format":            "PDF 1.6",
    "creation_date":     "2013-10-01",
    "modification_date": null,
    "encryption":        null
  },

  "pdf_profile": {
    // MUST HAVE — gates everything downstream.
    // "scanned" = no text layer = stop immediately, write stub.
    "pdf_type": "digital",

    // MUST HAVE — if false, fitz returns empty text. Extraction cannot run.
    "is_digital": true,

    // MUST HAVE for the future — today always false for digital PDFs.
    // When the OCR pipeline is built, importer uses this to route
    // scanned PDFs to a different processing path.
    "needs_ocr": false,

    // NICE TO HAVE — DTC adapter uses internal links to match codes to pages.
    // If false, adapter falls back to Y-position matching (lower confidence).
    // Helps importer understand how reliable the page references are.
    "has_links":          true,
    "has_internal_links": true
  },

  "vehicle": {
    // MUST HAVE — core identity. Every record stored in the database is
    // tagged with these. Without them you cannot answer
    // "which car does this code belong to?"
    "year":  "2013",
    "make":  "Nissan",
    "model": "LEAF",

    // NICE TO HAVE — some manuals cover multiple trims or battery sizes
    // (e.g. 24 kWh vs 40 kWh Leaf). Matters for part compatibility
    // and whether a procedure applies to a specific variant.
    "variant": null,

    // NICE TO HAVE — which revision of the manual this is.
    // Two manuals for the same car can differ if one is a later revision.
    // Importer can prefer the latest revision and flag older ones.
    "revision_date": "October 2013",

    // NICE TO HAVE — left-hand vs right-hand drive, or market region.
    // Wiring diagrams and procedures can differ by region.
    // Not extractable today — reserved for future.
    "region": null,

    // NICE TO HAVE — quick EV filter.
    // Importer and semantic search can scope queries to EVs only
    // without parsing any record content.
    "is_ev": true,

    // NICE TO HAVE — how and where vehicle info was found.
    // confidence lets importer decide whether to trust the value
    // or flag it for human review.
    // method records the detection path for debugging wrong extractions.
    "source": {
      "method":     "footer",   // footer | foreword | metadata | lookup
      "pdf_page":   1,
      "page_ref":   "EVB-1",
      "confidence": 0.95        // 0.0 – 1.0
    }
  },

  "section": {
    // MUST HAVE — namespaces all records in this file.
    // Single-section PDFs: ["EVB"]. Merged PDFs: ["GI", "EVB", "AV"].
    // Without this you cannot tell which section a record belongs to.
    "code": ["EVB"],

    // NICE TO HAVE — human-readable section name for display.
    // Not yet extracted. Useful in the UI and for search metadata.
    "name": null,

    // NICE TO HAVE — TYPE 1, TYPE 2 etc.
    // Some PDFs physically contain multiple manuals inside one file.
    // Importer uses this to split records correctly by manual type.
    "manual_type": null,

    // NICE TO HAVE — how many pages this section covers.
    // Importer can use this to detect partial extractions
    // (e.g. only 40 of 200 pages processed = something went wrong).
    "page_count": 200,

    // NICE TO HAVE — the printed page ref pattern used in this section.
    // Importer can validate that all page_refs in records look correct.
    // Future: useful when building cross-section reference linking.
    "page_ref_pattern": "EVB-{n}",

    // NICE TO HAVE — where on the page the ref was found.
    // Traceability for debugging wrong page refs.
    "page_ref_location": "footer"  // footer | header | sequential_fallback
  },

  "processing": {
    // MUST HAVE — which adapter wrote this file.
    // Importer routes differently per adapter.
    // First thing to check when debugging bad output.
    "adapter_name": "ev-pdf-codes-adapter",

    // NICE TO HAVE — version of the adapter's own payload schema (records[] shape).
    // Separate from schema_version. Importer can use this to detect old output
    // that needs re-extraction when the records[] format changes.
    "adapter_schema_version": 5,

    // MUST HAVE — machine-readable outcome. Importer acts on this field,
    // never on the errors[] strings.
    //
    //   "success"    — records extracted, ready to import
    //   "no_content" — valid PDF, no DTC codes found
    //                  (normal for procedure-only sections, skip silently)
    //   "scanned"    — no text layer, needs OCR in future
    //   "error"      — something broke, needs investigation
    //
    "extraction_status": "success",

    // MUST HAVE — convenience boolean for importer.
    // true only when extraction_status is "success".
    "extraction_completed": true,

    // NICE TO HAVE — when extraction finished.
    // Used to detect stale output that needs reprocessing
    // and to monitor pipeline throughput over time.
    "extracted_at": "2026-05-08T14:30:00",

    // NICE TO HAVE — non-fatal issues encountered during extraction.
    // Importer logs these, flags affected records for review,
    // or skips records tied to known bad errors.
    // Always an array — empty when no errors.
    "errors": []
  },


  // ═══════════════════════════════════════════════════════════════
  //  DTC ADAPTER SPECIFIC
  //  Only present in output from this adapter.
  //  The cars adapter (procedure extractor) will have different
  //  fields here — its records[] will contain procedure blocks,
  //  repair steps, torque specs, etc.
  //
  //  Both adapters are joined by document_id in the importer.
  // ═══════════════════════════════════════════════════════════════

  "records": [
    {
      // MUST HAVE — stable unique ID for this record.
      // Importer uses this to deduplicate on re-runs:
      // same record_id = update existing row, not insert new.
      "record_id": "a1b2c3d4e5f6a7b8",

      // MUST HAVE — what kind of record this is.
      // Importer routes to the right DB table or collection.
      // Cars adapter uses "procedure". This adapter uses "dtc_block".
      "record_type": "dtc_block",

      // MUST HAVE — the DTC codes this record covers.
      // Primary lookup key for the whole system.
      "codes": ["P0A0D"],

      // NICE TO HAVE — human-readable title.
      // Useful for display, search results, and quick triage.
      "title": "P0A0D HV SYSTEM INTERLOCK ERROR",

      // NICE TO HAVE — which TYPE N manual this belongs to.
      // Omitted (never null) when not detected.
      "manual_type": "TYPE 1",

      "location": {
        // MUST HAVE — source page range in the PDF.
        // Importer needs these to retrieve images and to link
        // records back to source for human verification.
        "start_pdf_page": 88,
        "end_pdf_page":   89,

        // NICE TO HAVE — printed page labels (EVB-88, EVB-89).
        // More stable than PDF page numbers — if the PDF is re-exported
        // with different pagination, printed labels stay the same.
        "page_refs": ["EVB-88", "EVB-89"],

        // NICE TO HAVE — section code at record level.
        // Needed when a single PDF spans multiple sections.
        "section_code": "EVB"
      },

      // MUST HAVE — text content for embedding and semantic search.
      // Without sections the record has structure but no searchable content.
      "sections": [
        {
          "section_id": "r1_s1",

          // MUST HAVE — the heading this text sits under.
          // Importer uses this for display and to weight embeddings
          // differently by heading type.
          "heading": "DTC Logic",

          // MUST HAVE — classified role.
          // Importer routes to the right embedding model or DB column.
          // description | dtc_logic | dtc_confirmation_procedure | diagnosis_procedure
          "role": "dtc_logic",

          // MUST HAVE — cleaned prose text. This is what gets embedded.
          // Noise filtered, hyphenation repaired, sidebar tabs stripped.
          "cleaned_text": "Monitors HV interlock circuit...",

          // NICE TO HAVE — OEM content ID (Nissan INFOID).
          // Links back to OEM documentation system.
          // Null for non-Nissan manuals. Future: other OEMs have equivalent IDs.
          //
          // Known pattern (Nissan): INFOID is assigned per content block, not per
          // heading. Some sections (e.g. DTC Confirmation Procedure) have null
          // because Nissan considers them part of the preceding content block.
          // null = no new block started here, not a missing value.
          // The adapter reports what the PDF says — it does NOT carry forward or
          // inherit the previous section's INFOID. That interpretation belongs
          // to the importer if it ever needs it.
          "oem_content_id": "INFOID:0000000008745933",

          // NICE TO HAVE — raw unfiltered zone text.
          // Lets importer or human verify nothing important was stripped.
          // Removed by --slim flag for lean importer output.
          "raw_text": "...",

          "page_start": 88,
          "page_end":   88
        }
      ],

      // MUST HAVE — structured table data.
      // DTC manuals are table-heavy. Most diagnostic logic
      // lives in tables, not prose.
      "tables": [
        {
          "table_id":       "r1_t1",
          "section_id":     "r1_s1",
          "heading_nearby": "DTC Logic",
          "role":           "dtc_logic",
          "start_pdf_page": 88,
          "end_pdf_page":   88,
          "page_refs":      ["EVB-88"],

          // MUST HAVE — raw structured rows. Source of truth for all table data.
          // Everything else (cleaned_table_text) is derived from this.
          "raw_rows": [
            ["DTC",   "Detected Item",     "Malfunction Cause"],
            ["P0A0D", "HV interlock open", "Connector loose or damaged"]
          ],

          // NICE TO HAVE — pipe-rendered, cleaned version for embedding.
          // Importer can embed this directly without re-rendering raw_rows.
          // Removed by --slim flag.
          "cleaned_table_text": "DTC | Detected Item | Malfunction Cause\nP0A0D | HV interlock open | Connector loose or damaged",

          "extraction": {
            // NICE TO HAVE — overall quality signal.
            // Importer flags low-confidence tables for human review.
            "confidence": "high",   // high | medium | low

            // NICE TO HAVE — specific issues found during extraction.
            // Importer decides how much to trust this table per flag.
            "quality_flags": [],

            // NICE TO HAVE — how many rows are headers vs data.
            // Importer skips header rows when embedding and when
            // displaying the table.
            "header_rows_hint": 1,

            // NICE TO HAVE — true when header detection is uncertain
            // (3+ level headers). Importer treats table with extra caution.
            "partial": false
          }
        }
      ],

      // NICE TO HAVE — tables merged across pages.
      // Importer uses these when a procedure spans multiple pages
      // and needs the full table in one place.
      "table_groups": [],

      // NICE TO HAVE — extracted images.
      // Importer stores and links these to records for display.
      // Essential once the frontend shows visual procedures.
      "images": [
        {
          "image_id":   "r1_i1",
          "section_id": null,       // not yet implemented
          "pdf_page":   89,
          "page_ref":   "EVB-89",
          "image_path": "EVB-89-img1.png",
          "caption":    "JPCIA0347ZZ",
          "role":       "unknown"   // not yet implemented
        }
      ],

      // NICE TO HAVE — non-fatal notes from extraction.
      // e.g. "merged 2 tables across pages: EVB-88, EVB-89"
      // Audit trail — importer can log these.
      "notes": [],

      "extraction": {
        // NICE TO HAVE — per-record extraction status.
        "status": "success",

        // NICE TO HAVE — always false for digital PDFs today.
        // Critical once OCR is added — importer must know if text came
        // from OCR (lower confidence) vs native PDF text layer.
        "ocr_used": false,

        // NICE TO HAVE — per-record warnings, finer-grained than
        // processing.errors at the top level.
        // Examples:
        //   "skipped image xref=1234 on page EVB-45: cannot decode image with filter /JBIG2Decode"
        //   "page_ref mismatch on PDF page 88: index=EVB-88, footer=EVB-89"
        //   "unknown heading (not in KNOWN_HEADINGS): 'Wiring Diagram'"
        "warnings": []
      }
    }
  ]

}
```

---

## What changes in a stub (no records found)

When no DTC codes are found, or the PDF is scanned, the adapter writes a stub.
Records is empty. The `processing` block tells the importer exactly why:

```jsonc
"processing": {
  "adapter_name":           "ev-pdf-codes-adapter",
  "adapter_schema_version": 5,
  "extraction_status":      "no_content",  // or "scanned" or "error"
  "extraction_completed":   false,
  "extracted_at":           "2026-05-08T14:30:00",
  "errors":                 ["no DTC codes found"]
},
"records": []
```

The importer checks `extraction_status` — one field, fixed values, no string parsing.

---

## Difference between this adapter and the cars adapter

| | **PDF Codes Adapter (you)** | **PDF Cars Adapter (colleague)** |
|---|---|---|
| What it extracts | DTC diagnostic records only | Everything — procedures, specs, steps, diagrams |
| How it navigates | Finds DTC index table → follows links to DTC pages only | Reads the whole document page by page |
| `record_type` | `"dtc_block"` | `"procedure"` (or similar) |
| Key content fields | `codes[]`, `sections[]`, `tables[]` | `steps[]`, `specs{}`, etc. |
| Shared profile | Identical | Identical |
| Joined by | `document_id` | `document_id` |

Both files for the same PDF share the same `document_id`.
The importer joins them to give the full picture:
diagnostic codes **and** repair procedures for the same vehicle.
