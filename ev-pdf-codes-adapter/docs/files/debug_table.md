# debug_table.py

Manual debug tool — renders a single PDF page to the terminal.
**Not part of the production pipeline.**

---

## Usage

```
python src/debug_table.py "manuals/EVB.pdf" 122
```

---

## What it prints

1. **Full page text** — first 600 chars of raw page text
2. **Table detection** — count, bbox, row/col count, raw cell content for every table PyMuPDF finds
3. **Drawn lines** — all horizontal/vertical lines and rectangles (table borders, rules)
4. **Sidebar zone** — all words in the rightmost 80 pts (sidebar tab detection)

---

## When to use

- Investigating why a specific table is extracted incorrectly
- Checking bbox coordinates and column boundaries on a problem page
- Verifying which drawn lines PyMuPDF sees (used by `_get_line_extent` and `_drawn_table_rect` in `content_extractor.py`)
- Diagnosing sidebar character false positives
