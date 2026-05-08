"""
debug_table.py
==============
Inspect what PyMuPDF detects on a single page — table bboxes,
column boundaries, and raw cell content.

Usage:
    python src/debug_table.py "manuals/2011 Nissan Leaf Workshop Manual for EVB.pdf" 617
"""

import sys
import fitz
from pathlib import Path


def debug_page(pdf_path: Path, pdf_page: int):
    """
    pdf_page — 1-based page number (matches our pipeline convention).
    """
    with fitz.open(str(pdf_path)) as pdf:
        total = len(pdf)
        if pdf_page < 1 or pdf_page > total:
            print(f"Page {pdf_page} out of range (PDF has {total} pages)")
            return

        page = pdf[pdf_page - 1]   # fitz is 0-indexed
        pw, ph = page.rect.width, page.rect.height
        print(f"\nPDF : {pdf_path.name}")
        print(f"Page: {pdf_page}  (size: {pw:.0f} x {ph:.0f} pts)")

        # ── Full page text (first 600 chars) ─────────────────────────────────
        full_text = page.get_text("text").strip()
        print(f"\n── Full page text (first 600 chars) ──────────────────────────")
        print(full_text[:600])

        # ── Table detection ───────────────────────────────────────────────────
        finder = page.find_tables()
        tables = finder.tables

        print(f"\n── Tables detected: {len(tables)} ────────────────────────────")

        for t_idx, table in enumerate(tables):
            bbox = table.bbox   # (x0, y0, x1, y1)
            print(f"\n  Table {t_idx + 1}")
            print(f"    bbox      : x0={bbox[0]:.1f}  y0={bbox[1]:.1f}  x1={bbox[2]:.1f}  y1={bbox[3]:.1f}")
            print(f"    page width: {pw:.1f}  —  right margin: {pw - bbox[2]:.1f} pts")

            # Column x-boundaries from the header row
            rows = table.extract()
            if not rows:
                print("    (no rows extracted)")
                continue

            print(f"    rows      : {len(rows)}")
            print(f"    cols      : {len(rows[0]) if rows[0] else 0}")

            # ── Column x-ranges from the table object ─────────────────────────
            try:
                col_headers = table.header
                print(f"    header    : {col_headers}")
            except Exception:
                pass

            # ── Raw rows ──────────────────────────────────────────────────────
            print(f"\n    Raw rows:")
            for r_idx, row in enumerate(rows):
                cells = [repr(c) if c else "''" for c in row]
                print(f"      [{r_idx}] {cells}")

        # ── Drawn lines / rectangles (table borders) ─────────────────────────
        # get_drawings() returns all vector graphics — lines, rects, curves.
        # Table borders show up as horizontal/vertical lines with consistent width.
        drawings = page.get_drawings()
        print(f"\n── Drawn lines on page ({len(drawings)} total) ────────────────────")
        print("   All horizontal/vertical lines and rectangles (any width):")
        for d in drawings:
            width  = d.get("width")
            color  = d.get("color")
            fill   = d.get("fill")
            for item in d.get("items", []):
                kind = item[0]
                if kind == "l":          # straight line
                    x0, y0 = item[1]
                    x1, y1 = item[2]
                    is_horiz = abs(y1 - y0) < 1
                    is_vert  = abs(x1 - x0) < 1
                    if is_horiz or is_vert:
                        direction = "H" if is_horiz else "V"
                        print(f"    {direction}  x0={x0:.1f} y0={y0:.1f} -> x1={x1:.1f} y1={y1:.1f}  width={width}  color={color}")
                elif kind == "re":       # rectangle
                    rect = item[1]
                    print(f"    R  x0={rect.x0:.1f} y0={rect.y0:.1f} x1={rect.x1:.1f} y1={rect.y1:.1f}  width={width}  fill={fill}  color={color}")

        # ── Words near right edge (sidebar detection) ─────────────────────────
        # Show all words in the rightmost 80 pts — these are likely sidebar tabs
        right_zone = fitz.Rect(pw - 80, 0, pw, ph)
        right_words = page.get_text("words", clip=right_zone)
        print(f"\n── Words in right 80pt margin (sidebar zone) ─────────────────")
        for w in right_words:
            print(f"    x0={w[0]:.1f}  y0={w[1]:.1f}  x1={w[2]:.1f}  y1={w[3]:.1f}  text={w[4]!r}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python src/debug_table.py <pdf_path> <page_number>")
        print('Example: python src/debug_table.py "manuals/EVB.pdf" 5')
        sys.exit(1)

    pdf_path = Path(sys.argv[1])
    if not pdf_path.exists():
        print(f"File not found: {pdf_path}")
        sys.exit(1)

    try:
        page_num = int(sys.argv[2])
    except ValueError:
        print(f"Page number must be an integer, got: {sys.argv[2]}")
        sys.exit(1)

    debug_page(pdf_path, page_num)
