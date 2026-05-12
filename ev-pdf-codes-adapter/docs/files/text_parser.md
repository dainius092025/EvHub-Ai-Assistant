# text_parser.py

Heading registry and noise filter for the extraction pipeline.
Consumed by `content_extractor.py` for section boundary detection and text cleaning.

---

## What this file does

- Defines `KNOWN_HEADINGS` — the authoritative list of section headings and their roles
- Builds `HEADING_LOOKUP` — a normalised dict for O(1) heading matching at runtime
- Provides `normalize_heading()` — case/whitespace normalisation for heading comparison
- Provides `is_noise()` — line-level noise filter used when cleaning extracted text

---

## Module-level constants

### `KNOWN_HEADINGS`
List of `(display_name, role)` tuples. One entry per recognised section heading.

Currently contains Nissan / Infiniti headings only — confirmed on 2013 Nissan LEAF (EVB.pdf, 204 codes).

| Heading | Role |
|---|---|
| `Description` | `description` |
| `DTC Logic` | `dtc_logic` |
| `DTC Confirmation Procedure` | `dtc_confirmation_procedure` |
| `Diagnosis Procedure` | `diagnosis_procedure` |
| `Component Inspection` | `component_inspection` |

Headings for other manufacturers (Toyota, Hyundai/Kia, VAG, BMW, Renault) live in
`shared/heading_seeds/<manufacturer>.json`. They are **not added here until confirmed
on a real PDF** from that manufacturer — unconfirmed headings can match table column
headers or other content in known-good PDFs and produce false section splits.

### `HEADING_LOOKUP`
`dict[str, tuple[str, str]]` — normalised heading text → `(display_name, role)`.
Built at import time from `KNOWN_HEADINGS`. Use this for matching instead of iterating
the list directly.

### `NOISE_PATTERNS`
List of compiled regexes. A line matching any of these is discarded by `is_noise()`.

| Pattern | Matches |
|---|---|
| `^Revision:\s+` | Revision headers e.g. `"Revision: 2014 June"` |
| `^< DTC/CIRCUIT DIAGNOSIS >$` | DTC section banner printed at page tops |
| `^[A-Z]{2,4}-\d+$` | Standalone page refs e.g. `"EVB-88"` |
| `^[PBCU][0-9A-F]{4}\s+[A-Z]…$` | DTC title repeated as page continuation header |
| `^\d{4}\s+[A-Z]…$` | Year + model name printed on every page e.g. `"2013 LEAF"` |

Noise patterns must remain manufacturer-agnostic — do not add model names or brand-specific strings.

---

## Functions

### `normalize_heading(text)`
Strips whitespace, collapses internal runs to a single space, lowercases.
`"  DTC  Logic  "` → `"dtc logic"` → matches `"DTC Logic"` in `HEADING_LOOKUP`.

### `is_noise(line)`
Returns `True` if the line matches any entry in `NOISE_PATTERNS`.
Called per line in `clean_text()` inside `content_extractor.py`.

---

## How to add a new manufacturer

1. Ask a sample PDF or GPT: "What are the DTC section heading names used in `<Manufacturer>` workshop manuals?"
2. Add a group in `KNOWN_HEADINGS` with a comment marking the manufacturer.
3. Map each heading to the closest role from the fixed set: `description | dtc_logic | dtc_confirmation_procedure | diagnosis_procedure | component_inspection`
4. No other code changes needed — `HEADING_LOOKUP` is rebuilt automatically at import.

Graduate from seed → production only after confirming on a real PDF from that manufacturer.
