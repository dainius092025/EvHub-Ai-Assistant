# diag.py

One-off noise analysis script — finds lines that appear on more than 50% of pages.
**Not part of the production pipeline.**

---

## What it does

Loads a pipeline output JSON, iterates all page records, counts how many pages each
unique line appears on, and prints lines above the 50% threshold. Used to identify
recurring noise that should be added to `NOISE_PATTERNS` in `text_parser.py`.

---

## Notes

- Hardcoded to an old JSON path (`data/2011 Nissan Leaf Workshop Manual for EVB/…`) — update the path before running
- References a `"pages"` top-level key and `dtc_logic_block` / `diagnosis_procedure_block` fields from a prior schema version — **will not work against current output** without modification
- Kept for reference; the pattern it identified helped build the `NOISE_PATTERNS` list
