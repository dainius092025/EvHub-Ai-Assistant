# Adding a New Manufacturer

This guide explains what to change when you want to run the pipeline on a PDF
from a manufacturer that has not been tested before.

The pipeline will not crash on an unknown manufacturer — it degrades gracefully.
The checklist below tells you what to fix so the output is complete and correct.

---

## Checklist

### 1. Run the pipeline first

```
python src/pipeline.py manuals/<YOUR_PDF>.pdf
```

Look at `processing.errors` in the output JSON and at the terminal output.
You will see warnings like:

```
[WARN unknown-heading] "Troubleshooting Hint" on page EVB-44 — not in KNOWN_HEADINGS
```

These tell you exactly which headings the new manual uses that are not yet recognised.

---

### 2. Add the new section headings — `src/text_parser.py`

Open [text_parser.py](../src/text_parser.py) and find the `KNOWN_HEADINGS` list.

Add a group for the new manufacturer:

```python
# ── Toyota / Lexus ────────────────────────────────────────────────────────
# Confirmed on: 2022 Toyota bZ4X (BZ4X.pdf)
("Conditions for Setting the DTC",  "dtc_logic"),
("Confirmation Driving Pattern",     "dtc_confirmation_procedure"),
("Troubleshooting Hint",             "description"),
("Circuit Inspection",               "component_inspection"),
```

**Role values** (pick the closest match):

| Role | Meaning |
|---|---|
| `description` | What the DTC means, system overview |
| `dtc_logic` | When/why the code sets |
| `dtc_confirmation_procedure` | How to reproduce the fault |
| `diagnosis_procedure` | Step-by-step diagnostic tree |
| `component_inspection` | How to test a specific component |

> Only add headings you have confirmed in a real PDF from that manufacturer.
> Unconfirmed headings can split sections incorrectly on other PDFs.

---

### 3. Add the model name to the vehicle lookup — `shared/vehicle_lookup.json`

If the pipeline outputs `"make": null`, the model name is not in the lookup file.

Open [vehicle_lookup.json](../../shared/vehicle_lookup.json) and add an entry:

```json
{
  "BZ4X": "Toyota",
  "IONIQ6": "Hyundai"
}
```

Key = model name in uppercase, value = make as it should appear in the output.

---

### 4. Check the DTC index heading — `src/patterns.py`

Open [patterns.py](../src/patterns.py) and look at `DTC_INDEX_HEADINGS`.

If the new manual uses a heading not in the set (e.g. "Diagnostic Trouble Code Chart"),
add it as a lowercase string. Run the pipeline again — the index scan will now find it.

> If you are not sure what the index page is called, open the PDF and search for the
> page that lists all the codes in a table with page references next to them.

---

## What does NOT need changing

| File | Why it is already generic |
|---|---|
| `patterns.py` — `CODE_RE` | Matches all standard OBD-II code formats (P/B/C/U + 4 hex digits) |
| `patterns.py` — `REF_RE` | Matches any `XX-123` style page reference |
| `vehicle_info.py` | Footer, foreword, and metadata detection use generic regexes |
| `pdf_profile.py` | Pure technical PDF analysis — no brand assumptions |
| `content_extractor.py` | INFOID stripping is Nissan-specific but harmless — just produces no matches |
| `type_detector.py` | TYPE N variant detection returns `None` gracefully if not found |

---

## If the index page is not found at all

The pipeline will output `"extraction_status": "no_content"` with zero records.

Likely cause: the index heading is not in `DTC_INDEX_HEADINGS`.
Fix: add it (see step 4 above).

If the index page uses a completely different structure (no table, codes only in prose),
that requires deeper work in `index_builder.py` — file a GitHub issue with a sample page.
