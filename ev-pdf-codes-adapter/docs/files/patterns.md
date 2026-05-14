# patterns.py

Compiled regex constants shared across the pipeline.
Imported by `content_extractor.py`, `extractor.py`, and `index_builder.py`.

---

## Constants

| Name | Pattern | Matches | Used for |
|---|---|---|---|
| `CODE_RE` | `^[PBCU][0-9A-F]{4}$` | DTC codes: `P0A0D`, `B1234`, `C3456`, `U0100` | DTC index building (`index_builder.py`) |
| `DTC_INDEX_HEADINGS` | frozenset of lowercase strings | All known DTC index page headings across manufacturers — including ambiguous ones like `"self-diagnosis results"` | Heading scan fallback in `index_builder.py` |
| `DTC_INDEX_HEADINGS_STRICT` | frozenset (subset of above) | Unambiguous DTC index headings only — excludes `"self-diagnosis results"` and similar headings that also appear as subsections inside content pages | Bookmark matching in `index_builder.py` — prevents subsection bookmarks from being mistaken for index page bookmarks |
| `REF_RE` | `[A-Z]{2,10}-(\d+)` | Page references: `EVB-123`, `TM-44` | Page ref extraction |
| `SIDEBAR_RE` | `^\s*[A-Z]\s*$` (multiline) | Single uppercase letters on their own line — PDF sidebar nav tabs (A, B, C…) | Sidebar character stripping in `clean_text()` |
| `INFOID_RE` | `INFOID:\d+` | Nissan OEM content IDs: `INFOID:0000000005277155` | Stripped from section text in `clean_text()`; extracted as `oem_content_id` |
| `IMAGE_ID_RE` | `^[A-Z]{1,8}[0-9]{2,}[A-Z0-9]{0,8}$` | OEM figure codes: `JSCIA0812GB`, `JPCIA0347ZZ` | Image caption detection; image-box table filter |

---

## Notes

- `SIDEBAR_RE` is intentionally limited to a **single letter** so decision labels (`YES`, `NO`) are preserved.
- `IMAGE_ID_RE` is manufacturer-agnostic — matches the structural pattern (letters + digits + alphanumeric suffix) without hardcoding any brand prefix.
- `INFOID_RE` is Nissan-specific by content but causes no harm on non-Nissan PDFs — it simply never matches.
