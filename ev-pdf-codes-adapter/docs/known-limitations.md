# Known Limitations

Limitations discovered during testing across real-world PDFs.
These are source data constraints — not bugs in the pipeline.

---

## 1. Grouped codes pointing to first page of group (not their specific page)

**Affected codes:** P303D – P3048 (Nissan Leaf Workshop Manual, EVB section)

**What happens:**
The DTC index on the EVB section index page uses a single reference cell (`EVB-62`)
for the entire P3031–P3048 battery module ASIC group. The index does not individually
reference `EVB-63` (which is the dedicated content page for P303D–P3048).

As a result, all codes in the carry-forward chain are assigned `EVB-62` (page 576)
even though P303D–P3048 have their own page at `EVB-63` (page 577).

**Why it happens:**
The Nissan DTC index for large battery module code groups uses one reference entry to
cover multiple sub-pages. This is an authoring decision in the source PDF — the index
does not provide the granularity to distinguish between sub-pages in the group.

**Impact:**
The content extractor will process the group from `EVB-62` rather than the more
specific `EVB-63`. `EVB-62` does include a cross-reference table listing the affected
codes, so the record is not empty — but it may miss content specific to `EVB-63`.

**Can it be fixed?**
Not at the index stage. Would require content-page analysis: detecting when a code
appears in a page's DTC table but is not the primary code for that page, then
redirecting to the more specific page. Out of scope for the current pipeline.

---

## 2. Cross-section references with no hyperlinks

**Affected codes:** P1610, P1611, P1612 (Nissan Leaf Workshop Manual, EVC section)

**What happens:**
Some DTC codes in one section (e.g. EVC) reference a procedure in a different section
(e.g. SEC — Security Control System). These cross-section references appear as plain
text in the index table (e.g. `SEC-51`, `SEC-52`, `SEC-53`) with no internal hyperlink
in the PDF.

**Why it happens:**
The PDF author did not add hyperlinks for cross-section references. The reference text
is printed but not linked.

**Impact:**
Without the footer scan fallback, these codes would be dropped from the index entirely.
With the fallback, they are resolved correctly via the footer scan map
(`SEC-51` → page 2461, etc.). Resolved as `[INFO]`, not dropped.

**Status:** Handled. Footer scan fallback resolves them correctly.

---

## 3. Hyperlinks and/or reference text authored to wrong destination page

**Affected codes:** P0A0D, P0A1F (Nissan Leaf Workshop Manual, EVB section)

**What happens:**
Two distinct authoring errors appear in the EVB DTC index:

- **P0A1F** — reference text says `EVB-60` but the hyperlink resolves to `EVB-61`.
  The cross-check detects the mismatch and the footer scan corrects it to page 574
  (EVB-60, the right page). **Handled.**

- **P0A0D** — reference text says `EVB-60` AND the hyperlink also goes to `EVB-60`.
  The cross-check sees no mismatch and trusts the assignment. But P0A0D's actual
  content starts at EVB-58 (page 572), not EVB-60. Both the index reference text
  and the hyperlink are wrong. **Not currently handled — P0A0D is assigned the
  wrong page.**

**Why it happens:**
PDF authoring errors. The visible reference text and the hyperlink destination were
set independently and not kept in sync when the manual was produced.

**Can it be fixed?**
P0A1F: already fixed via cross-check + footer scan.
P0A0D: requires content-page verification — scan the assigned page for the code
string, and if absent, search nearby pages. This is the motivation for the planned
`_verify_assignments()` pass in `build_index`.

---

## 4. PDF metadata title is an authoring tool artifact

**Affected files:** av.pdf (AV Control Unit section, 2011 Nissan Leaf Workshop Manual)

**What happens:**
The `metadata.title` field in the document profile is `"Config.book(AV.fm)"` — a
FrameMaker internal book/file reference, not a human-readable document title.

**Why it happens:**
The PDF was exported from Adobe FrameMaker without setting a proper document title.
FrameMaker writes its internal file reference into the PDF title metadata field.

**Impact:**
The adapter passes through `metadata.title` exactly as the PDF reports it.
The value is not useful as a display title.

**Importer guidance:**
Filter or discard `metadata.title` values that match a FrameMaker artifact pattern
(e.g. contains `.fm)` or `.book(`). The `source_file` field is the reliable identifier.

---
