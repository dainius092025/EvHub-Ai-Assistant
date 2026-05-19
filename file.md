# EV Manual PDF Extraction Pipeline — Architecture & Decision Log

**Project:** EV service manual extraction for LLM-powered mechanic assistant  
**Team:** Cars adapter (procedures) · Dainius (DTC adapter) · Luca (LLM agent / retrieval)  
**Hardware:** Dell Latitude E7450, i5-5300U, 8GB RAM  
**Target manuals:** Nissan Leaf 2015 — ha.pdf (121p), evb.pdf (259p), vc.pdf (146p)

---

## What this system does

Reads EV service manual PDFs and produces structured JSON that an LLM agent uses to help mechanics troubleshoot and repair high-voltage vehicles. The output must be accurate enough to be safety-critical — a mechanic acting on wrong procedure order or a missed warning could be seriously injured.

The pipeline runs on a laptop, not a server. Every architecture decision reflects that constraint.

---

## Phase 1 — Initial extraction prototype

### First look at the PDFs

Opened ha.pdf. Immediately identified it as a FrameMaker 7.1 → Acrobat Distiller digital PDF, not scanned. Key facts confirmed from the file:

- 121 pages, letter size (612 × 792 pts), PDF 1.5
- Full internal bookmark outline with 329 entries across 7 depth levels
- Footer pattern `HA-{n}` on every page — reliable page reference source
- Section navigation tabs (single capital letters A–P) on right margin — noise, not content
- INFOID reference codes (`INFOID:0000000010640902`) on every subsection — OEM document IDs, not useful to mechanics
- Variant tags (`[WITH HEAT PUMP SYSTEM]`) on almost every page header
- Breadcrumb tags (`< REMOVAL AND INSTALLATION >`) repeated at top of each page

EVB (259 pages) and VC (146 pages) confirmed identical structure. All three manuals use the same Nissan standard layout — fixing issues once fixes them for all.

### Tool selection

Evaluated three extraction approaches:

**Option A — pdfplumber only.** Good for simple text and tables. Loses reading order on complex multi-column pages and cannot extract images at all.

**Option B — pymupdf only.** Excellent for images and text with bounding boxes. Table extraction is unreliable for merged cells and nested headers.

**Option C — pymupdf + Docling (chosen).** pymupdf handles images and footer reading where it excels. Docling handles text with ML-based reading order and TableFormer for complex tables. Each tool does what it's best at.

Cost of this choice: Docling is slow. 150 pages takes roughly 10 minutes on the laptop. Acceptable for an offline batch pipeline.

### First working extractor — `optimized_parser.py`

Built a two-pass parallel extractor using ThreadPoolExecutor. Pass 1 was a fast Docling scan. Pass 2 conditionally ran TableFormer if tables were detected. Workers ran in parallel batches.

This worked but had problems. It had a hardcoded PDF filename (`bMbG2Y1e3fHBv1Q6.pdf`), used threading which caused memory issues on 8GB RAM, and produced a different output format (`elements` key instead of `text_elements`) that nothing downstream could read. It was a prototype.

**Decision: replaced entirely by `extractor.py`. `optimized_parser.py` is dead code — delete it.**

---

## Phase 2 — Structured pipeline

### Architecture decision: single responsibility per file

Rather than one large extraction script, split into stages where each file does exactly one job and writes its output to disk. This means any stage can be re-run without redoing earlier stages, which matters a lot on a slow laptop.

```
detector.py        → raw/shared_profile.json
extractor.py       → raw/{start}_{end}.json + raw/images/
classifier.py      → output/{SECTION}_classified.json
contents_parser.py → raw/section_map.json
section_classifier.py → output/{SECTION}_sectioned.json
```

### `detector.py` — document identity

Runs before extraction. Determines whether the PDF is digital or scanned, finds the section code from the footer, detects the manufacturer from a lookup table, and writes `shared_profile.json`.

**document_id — UUID → SHA-256 (changed later, see Phase 4)**

Initial implementation used `uuid.uuid4()` for document_id. Changed to `hashlib.sha256(pdf.read_bytes()).hexdigest()` after aligning with Dainius's DTC adapter. SHA-256 of the file bytes is stable across runs and identical for the same PDF processed by both adapters. This is the key the importer uses to join procedure records to DTC records.

### `extractor.py` — raw extraction

Opens the PDF once. For each batch of pages runs a pymupdf pass (images + footer) then a Docling pass (text + tables). Two Docling converters are built once at startup — one with TableFormer, one without. TableFormer only activates when a batch contains a table with 4+ columns, which limits the RAM and time cost.

OCR detection per page: if extracted characters < 50, mark as scanned. These manuals are all digital so OCR never actually triggers, but the detection is there for future multi-manufacturer support.

Batch files are internal working files only. They exist so the pipeline can resume if interrupted — a batch file already on disk is skipped.

### `classifier.py` — noise removal and element tagging

Three jobs in one pass over the raw batch files:

**Job 1 — noise removal.** Five types of noise identified from manual inspection and removed before tagging runs:
- Single capital letters in the right margin (A–P section navigation tabs) — detected by bounding box x-position > 560
- Tiny inline symbols (•, ◦, ■ etc.) — wiring diagram artefacts
- INFOID codes (`INFOID:\d+`) — OEM document tracking IDs
- Variant tags (`[WITH HEAT PUMP SYSTEM]`) — page header noise
- Breadcrumb tags (`< REMOVAL AND INSTALLATION >`) — page navigation context, not content

**Job 2 — element tagging.** Every text element gets a `type` field: `warning_header`, `warning`, `section_header`, `procedure_step`, `spec_value`, or `general_text`. Safety level (`HIGH_VOLTAGE`, `WARNING`, `CAUTION`, `NONE`) assigned by keyword matching.

**Warning merge fix — EVB-200 pattern.** Initial implementation merged every `warning_header` with the next element. Discovered on EVB page 200 that WARNING blocks can sit between numbered procedure steps, not just before them. Merging a `warning_header` with a `procedure_step` would absorb the step into the warning body — a safety-critical error. Fixed: warning merge only fires if the next element is NOT a `procedure_step`.

**Job 3 — table repair.** Merged cells in Docling's table output leave empty cells in the left columns of spec tables. Forward-fill applied to columns where >40% of cells are empty. Restores the hierarchy lost from merged cells (e.g. "Camber → Minimum / Nominal / Maximum").

**Table type detection:**
- `toc` — dot-leader tables from the visual contents pages. Noise, skipped in section assignment
- `index_table` — section code tables (HA, EVB, VC mappings)
- `spec_table` — service data with merged left columns
- `general` — everything else

### `config.py` — single source of truth

All constants, regex patterns, thresholds, and Nissan-specific noise patterns in one file. Nothing is hardcoded in the pipeline modules. This was introduced after the second iteration when the same patterns were being duplicated across classifier and extractor.

---

## Phase 3 — Chunking (future reference only)

`chunker.py` and `assembler.py` were built in this phase but are now superseded by section reconstruction. They are moved to `future/`. The section classifier produces the final output directly from the PDF's own structure rather than from heading-based chunking.

### What chunker.py did and why it was superseded

Chunker walked the classified element stream and split it into chunks at `section_header` boundaries. Each chunk was one procedure unit — heading, steps, warnings, tables, images.

Problems discovered:

**chunk_type detection.** Initial version had no chunk type — every chunk was implicitly a procedure. Added `chunk_type` (`precaution`, `procedure`, `description`) after seeing that precaution pages (HA-4, HA-5 — safety briefings with no numbered steps) were being incorrectly flagged for missing prerequisites. Precaution chunks ARE the safety content — they don't need prerequisites themselves.

**prerequisite detection.** Initial regex matched prerequisite language ("before", "ensure", "verify") anywhere in the first 5 elements. Most Nissan procedures have DANGER/WARNING blocks immediately before step 1 — these are the actual prerequisites. Rewrote to treat every `warning` element appearing before the first `procedure_step` as a prerequisite, with keyword matching as a fallback.

**cross-page table merging.** Docling extracts cross-page tables as two separate objects with identical headers. Added `_merge_cross_page_tables()`: consecutive tables in the same section with matching header rows are merged into one. Data rows from the second table are appended, header skipped.

**validate.py** was the original standalone validator for chunks.json. Superseded by `validator.py`. Delete it.

**assembler.py** read chunks.json and added flat text for embedding plus a section index. Phase 2+ work. Moved to `future/`.

---

## Phase 4 — Section reconstruction (current architecture)

### The core problem with chunking

Chunking splits at `section_header` elements — text elements tagged as headings. But Docling's heading detection is imperfect for FrameMaker PDFs. Some headings were missed, some content was misclassified as headings. The real section structure was already embedded in the PDF itself — the internal bookmark outline had 329 entries with exact page numbers and Y coordinates.

**Decision: use the PDF's own structure to reconstruct sections.**

The PDF outline gives us: title, level (0–6), PDF page number, and Y coordinate from the bottom of the page (`/Top` field in the destination object). This is more reliable than anything Docling detects because it is what the original publisher encoded.

### `contents_parser.py` — section map from PDF outline

Reads `doc.get_toc()` via pypdf. Extracts Y coordinates from the `/Top` field of each destination object. Assigns end boundaries by finding the next entry at the same or shallower depth — this was a subtle bug in the first implementation which used the next entry regardless of depth, causing child sections to incorrectly end at sibling boundaries.

**Critical bug fixed:** `doc.page_count` was called after `doc.close()`. Fixed by saving the count before closing.

Writes `raw/section_map.json` with the full section tree including page ranges and Y coordinates.

**Fallback for PDFs without outline:** Visual TOC dot-leader parsing as fallback for future multi-manufacturer support (Chevrolet Bolt has no internal outline). Not used for current Nissan manuals.

**`structural_authority` field:** Records which source was used to build the section map (`pdf_outline`, `pdf_contents_pages`, etc.) and what the fallback chain is. Required by `section_classifier.py` to decide how to interpret boundaries.

### `section_classifier.py` — element assignment to sections

Reads the section map and the classified elements. Assigns each element to the deepest (most specific) section whose boundary contains it.

**Coordinate system:** Docling bbox[1] is Y from the top of the page. PDF outline `/Top` is Y from the bottom. Conversion: `pdf_y = 792 - bbox[1]`. Page height confirmed as 792 pts from `pdfinfo`.

**Assignment logic:** For each element, find all sections whose page range contains the element's page. On a multi-section page, use Y coordinate to pick the correct section. When multiple sibling sections qualify on the same page, pick the one with the largest `top_y_start` value — the closest heading above the element.

**`MIN_ASSIGNMENT_LEVEL = 2`:** L0 and L1 entries are structural containers (e.g. "WITH HEAT PUMP SYSTEM" spanning the entire document). Assigning content to them would be meaningless. Elements are only assigned to L2 and deeper sections.

**`merged_text_full` removed:** Initially `section_classifier.py` produced both `merged_text` (direct elements only) and `merged_text_full` (elements from all descendants). This caused content duplication in every parent section. Removed. Each section now has only `merged_text` from its direct elements.

**Reading order known limitation:** Docling returns `reading_order = None` for all elements in these manuals. Sort falls back to Y position (bbox[1], lower = higher on page). For pages where the FrameMaker PDF content stream order differs from visual order (some bullet lists), the merged text order may not perfectly match the printed page. Content is correct — only ordering within a section may occasionally differ.

---

## Phase 5 — Shared output contract

### Why a shared contract matters

Both adapters (cars adapter and Dainius's DTC adapter) process the same PDFs. Luca's importer joins their outputs using `document_id`. If the field names or computation methods differ, the join fails silently and the importer never links procedure records to DTC records.

Dainius provided his full output contract as documentation. After comparison:

**Fields that matched cleanly:** schema_version, schema_type, source_file, metadata, pdf_profile, vehicle, section — all compatible.

**`document_id` — critical mismatch resolved.** Cars adapter was using `uuid.uuid4()`. Dainius uses SHA-256 of the PDF file bytes. Changed to `hashlib.sha256(pdf.read_bytes()).hexdigest()`. Now both adapters produce identical document_id for the same PDF.

**`processing` block — structure mismatch resolved.** Cars adapter had `procedure_extraction_completed: bool` and `dtc_extraction_completed: bool`. Adopted Dainius's cleaner structure: `adapter_name`, `extraction_status` (enum: pending/success/no_content/scanned/error), `extraction_completed`, `extracted_at`, `errors[]`.

**`content_split` — removed.** Was a block describing which page ranges belonged to which adapter. Not needed — each adapter processes its own content and the importer joins by document_id.

**`structural_authority` — kept, cars adapter only.** Required by contents_parser.py and section_classifier.py. Not in Dainius's contract, but `additionalProperties: true` in the shared schema means his output won't fail validation when this field is absent from his files.

### Schema files

`shared_profile.schema.json` — the agreed contract between both adapters. `additionalProperties: true` so each adapter can include its own extra fields without the other's output failing validation.

`raw_batch.schema.json` — internal only. Validates extractor output during development.

`classified_batch.schema.json` — internal only. Validates classifier output during development.

`cars_adapter.schema.json` — deleted. Was an `allOf` wrapper that added no real validation beyond the shared schema.

---

## Final output shape

Every `{SECTION}_sectioned.json` contains:

```
Shared profile fields (identical in both adapters)
  schema_version, schema_type, document_id, source_file,
  metadata, pdf_profile, vehicle, section, processing

Cars adapter specific
  structural_authority   ← how section structure was determined
  sections[]             ← hierarchical section tree
    section_id, record_type, title, level
    location { start_pdf_page, end_pdf_page, page_refs[], section_code }
    merged_text           ← all direct element text in reading order
    tables[], images[], notes[]
    extraction { status, ocr_used, warnings[] }
    children[]            ← nested sections, same shape
  unassigned[]            ← elements that could not be assigned
```

---

## Final file inventory

### Active pipeline (keep)

| File | Role |
|------|------|
| `config.py` | All constants and patterns — single source of truth |
| `detector.py` | Stage 1: document identity, SHA-256 document_id |
| `extractor.py` | Stage 2: lossless raw extraction |
| `classifier.py` | Stage 3: noise removal and element tagging |
| `contents_parser.py` | Stage 4: PDF outline → section map |
| `section_classifier.py` | Stage 5: assign elements → sectioned output |
| `validator.py` | Advisory validation, runs once at end |
| `main.py` | Orchestration only — 6 steps |
| `schemas/shared_profile.schema.json` | Shared contract with DTC adapter |
| `schemas/raw_batch.schema.json` | Internal extractor validation |
| `schemas/classified_batch.schema.json` | Internal classifier validation |

### Delete now

| File | Reason |
|------|--------|
| `optimized_parser.py` | Early prototype, hardcoded filename, dead code |
| `validate.py` | Superseded by validator.py |
| `schemas/cars_adapter.schema.json` | allOf wrapper that adds no real validation |

### Move to `future/`

| File | Reason |
|------|--------|
| `splitter.py` | DTC boundary detection — Phase 3 work, not needed now |
| `chunker.py` | Semantic chunking — Phase 2 work |
| `assembler.py` | Chunk assembly — Phase 2+ work |

---

## Known limitations

**Docling reading order.** `reading_order` is always `None` for these PDFs. Sort falls back to Y position. FrameMaker content stream order occasionally differs from visual reading order within a section, most notably on pages with dense bullet lists.

**FrameMaker coordinate mismatch on shared pages.** When REMOVAL ends and INSTALLATION begins on the same page (e.g. HA-41), content above the INSTALLATION heading correctly stays in REMOVAL. Content below is correctly assigned to INSTALLATION. But FrameMaker stores some content in stream order rather than visual order, so merged_text within the INSTALLATION section on that page may not match the exact visual reading sequence. Content is complete and correct.

**OCR.** All three current manuals are digital PDFs. The OCR pipeline exists and routes correctly when `needs_ocr: true`, but has not been tested on real scanned input.

**Images.** File path and bounding box are extracted. Image content is not described. The agent team (Luca) handles Vision AI on their side.

---

## Roadmap

**Phase 1 (current):** Stable Nissan Leaf extraction. HA, EVB, VC. Full pipeline working end to end.

**Phase 2:** Semantic chunking on top of sectioned output. Luca's team to specify chunk size requirements. `chunker.py` in `future/` is the starting point.

**Phase 3:** Multi-manufacturer support (VW ID.4, Chevrolet Bolt). DTC boundary routing (`splitter.py`). Visual TOC fallback for PDFs without internal outline.