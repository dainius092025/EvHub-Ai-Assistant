# script_for_meta.py

One-off script — dumps raw PDF metadata to JSON.
**Not part of the production pipeline.**

---

## What it does

Opens `manuals/PWO.pdf`, reads its PyMuPDF metadata dict, and writes it to
`data/PWO_metadata.json`. Used as a quick inspection tool when investigating
a new PDF's document properties.

---

## Notes

- Hardcoded to `PWO.pdf` — edit the path to inspect a different PDF
- `profile_pdf()` in `pdf_profile.py` does the same thing (and more) as part of the pipeline; this script predates that module
