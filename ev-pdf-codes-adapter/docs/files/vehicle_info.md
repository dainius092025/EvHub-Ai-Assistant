# vehicle_info.py

Extracts vehicle make, model, year, variant, and revision date from a PDF.
Returns the `vehicle` block for the document-level JSON.

---

## What this file does

Runs a priority chain across multiple sources to populate vehicle fields:

| Field | Priority |
|---|---|
| `year`, `model`, `variant`, `revision_date` | footer → foreword → null |
| `make` | foreword → metadata → lookup → null |

The `source` block records exactly where each piece of information was found.

---

## Public functions

### `extract_vehicle_info(pdf_path, metadata)`
Returns a `vehicle` dict with fields: `year`, `make`, `model`, `variant`,
`revision_date`, `source`.

**Steps:**
1. **Footer** (`_parse_footer`) — reads the bottom 12% of page 1; extracts `revision_date`, `year`, `model`, `variant`
2. **Foreword** (`_try_foreword`) — scans first 10 pages for `"for the YYYY MAKE MODEL"` pattern; provides `make`, confirms `year` and `model`
3. **Metadata** (`_try_metadata`) — tries `"YYYY Make Model"` in the PDF title field; fills `make` if foreword failed
4. **Lookup** (`_load_lookup`) — derives `make` from model name via `shared/vehicle_lookup.json` if all else fails

---

## Private functions

| Function | Purpose |
|---|---|
| `_parse_footer(page)` | Reads last 3 non-empty lines of the footer area; extracts revision date and vehicle line |
| `_try_foreword(pdf)` | Scans first 10 pages for foreword text matching `_FOREWORD_RE`; returns `(info, pdf_page, page_ref)` |
| `_try_metadata(metadata)` | Parses `"YYYY Make Model"` from the PDF metadata title field |
| `_load_lookup()` | Loads `shared/vehicle_lookup.json`; maps model name → make |

---

## Regex patterns

| Name | Matches |
|---|---|
| `_REVISION_RE` | `"Revision: October 2013"` or `"Revision: 2010 November"` |
| `_PAGE_REF_RE` | Page refs like `"EVB-1"` — skipped in footer parsing |
| `_FOOTER_VEHICLE_RE` | `"2013 LEAF"`, `"LEAF"`, `"2015 Leaf NAM"` — groups: year, model, variant |
| `_FOREWORD_RE` | `"for the 2011 NISSAN LEAF"` — groups: year, make, model |

---

## Notes

- `make_from_lookup` flag is added to `source` when the lookup file resolved the make; `extractor.py` strips this before including `vehicle` in the output JSON
- Footer variant detection: if the regex puts a trailing 2–4 char uppercase word into `model`, it is split off as `variant` (e.g. `"Leaf NAM"` → model=`"Leaf"`, variant=`"NAM"`)
- Lookup file path: `shared/vehicle_lookup.json` (relative to repo root)
