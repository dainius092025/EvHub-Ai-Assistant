# Schema Changelog

Changes to the adapter output format, tracked from the point the importer dev
received the first JSON contract (`adapter_output.example.json`, 2026-05-17).

---

## 2026-05-18

### `title` no longer includes the DTC code prefix

**Before**
```json
"codes": ["P0A0D"],
"title": "P0A0D HV SYSTEM INTERLOCK ERROR"
```

**After**
```json
"codes": ["P0A0D"],
"title": "HV SYSTEM INTERLOCK ERROR"
```

**Why:** The code is already in `codes[]`. Repeating it in `title` is redundant
and causes double-display if the importer renders both fields. For multi-code
records the old title was a synthesised range string like
`"P3031-P303C CELL CONT"` — after the change it will just be `"CELL CONT"`.

**Importer impact:** Low. `codes` is unchanged. If you are currently displaying
`title` as-is, the code prefix will disappear from the rendered string.
No field added, removed, or renamed.

### `title` no longer includes trailing `[CODE]` bracket

Some index table cells contained the DTC code a second time in brackets at
the end of the display text (e.g. `"ACC NO CONN\n[U1A00]"`). This bracket is
now stripped from the title.

**Before**
```json
"codes": ["U1A00"],
"title": "ACC NO CONN [U1A00]"
```

**After**
```json
"codes": ["U1A00"],
"title": "ACC NO CONN"
```

**Importer impact:** None — the code is already in `codes[]`. The title is now
shorter and cleaner.

---
