# type_detector.py

Detects manual-level TYPE N boundaries in a PDF.

Some workshop manuals contain multiple logical manuals (TYPE 1, TYPE 2, …) inside
one physical PDF. This module scans all pages for explicit TYPE heading blocks and
returns a page-to-type mapping used by `extractor.py` to split multi-type records.

---

## What this file does

- Scans every page for a standalone text block matching exactly `"TYPE N"`
- Builds a `{pdf_page (1-based): "TYPE N" | None}` mapping
- Pages inherit the most recent TYPE heading seen — `None` until the first heading

---

## Public functions

### `detect_manual_types(pdf_path)`
Returns `dict[int, str | None]` — one entry per PDF page (1-based).

`None` on every page means no TYPE headings found. Callers treat this as
"no `manual_type`" and omit the field from output rather than writing `null`.

---

## Private functions

### `_detect_type_on_page(page)`
Returns `"TYPE N"` if the page contains a standalone TYPE N heading block, else `None`.
Only short text blocks are checked — avoids false positives inside body paragraphs.

---

## Module-level constants

| Name | Pattern | Matches |
|---|---|---|
| `_TYPE_RE` | `^TYPE\s+(\d+)$` | Exact block text `"TYPE 1"`, `"TYPE 2"`, etc. |

---

## Notes

- Page numbers are 1-based throughout (matching `index_builder.py` convention)
- The TYPE boundary split in `extractor.py` uses this map to restart `extract_content`
  from the boundary page under the new `manual_type` — no pages are dropped
- Prints a `[TYPE]` notice to stdout when a boundary is detected (visible in pipeline output)
