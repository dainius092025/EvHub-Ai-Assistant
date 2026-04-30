"""
type_detector.py
================
Detect manual-level TYPE N boundaries in a PDF.

Some workshop manuals contain multiple logical manuals (TYPE 1, TYPE 2, ...)
inside one physical PDF.  This module scans the PDF for explicit TYPE heading
blocks and returns a page-to-type mapping.

A TYPE heading is a text block whose entire text (stripped) matches exactly
"TYPE N" (case-insensitive, any integer N).

If no TYPE headings are found the mapping contains only None values — the
caller must treat manual_type as absent (omit from output, not null).

Returns: {pdf_page_num (1-based): "TYPE 1" | "TYPE 2" | ... | None}
  None  = page precedes first TYPE heading, or no TYPE headings found at all.
"""

import re
import fitz
from pathlib import Path

# Matches a complete block text of exactly "TYPE N"
_TYPE_RE = re.compile(r"^TYPE\s+(\d+)$", re.IGNORECASE)


def _detect_type_on_page(page) -> str | None:
    """
    Return "TYPE N" if this page contains a standalone TYPE N heading block,
    else None.

    A heading block is one whose entire stripped text matches TYPE N.
    Short blocks only — avoids false positives inside body paragraphs.
    """
    for block in page.get_text("blocks"):
        text = block[4].strip()
        m = _TYPE_RE.match(text)
        if m:
            return f"TYPE {m.group(1)}"
    return None


def detect_manual_types(pdf_path: Path) -> dict[int, str | None]:
    """
    Scan all pages and return a {pdf_page (1-based): manual_type} mapping.

    manual_type starts as None and updates whenever a TYPE N heading block is
    found.  All subsequent pages inherit that type until the next heading.

    If no TYPE headings are found every page maps to None — callers should
    treat this as "no manual_type detected" and omit the field from output.
    """
    result: dict[int, str | None] = {}
    current_type: str | None = None

    with fitz.open(str(pdf_path)) as pdf:
        for i in range(len(pdf)):
            page_num = i + 1          # 1-based, matches index_builder convention
            detected = _detect_type_on_page(pdf[i])
            if detected:
                current_type = detected
                print(f"  [TYPE] {detected} boundary at PDF page {page_num}")
            result[page_num] = current_type

    return result
