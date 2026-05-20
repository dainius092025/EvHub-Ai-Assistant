import re
import hashlib
import fitz
from pathlib import Path
from patterns import INFOID_RE, SIDEBAR_RE, IMAGE_ID_RE
from text_parser import KNOWN_HEADINGS, HEADING_LOOKUP, normalize_heading, is_noise

# Matches printed page labels found in PDF footers.
#
# Known formats (expand this list as new manufacturers are encountered):
#   EVB-88    Nissan section-prefixed labels (2–4 uppercase letters)
#   TM-44     Short section prefix
#   A-1       Single-letter prefix (Toyota, some others)
#   A-1A      Single-letter prefix + trailing letter suffix
#   A-12B     Single-letter prefix + multi-digit number + trailing letter
#
# Pattern breakdown:
#   [A-Z]{1,4}  — section prefix: 1 to 4 uppercase letters
#   -           — required dash separator
#   \d+         — one or more digits
#   [A-Z]?      — optional trailing letter suffix (e.g. the 'A' in 'A-1A')
#
# NOTE: to add a new format, extend the prefix length or suffix rule here
# and add an example to the known-formats list above.
_PAGE_REF_RE = re.compile(r'\b([A-Z]{1,4}-\d+[A-Z]?)\b')

# Matches sidebar navigation tab values: single uppercase letters (A, B, C…)
# or short section codes (EVB, EVC) — never table data.
_SIDEBAR_VAL_RE = re.compile(r'^[A-Z]{1,4}$')


def _is_image_box_table(rows: list[list]) -> bool:
    """
    Return True when a table is a wiring-diagram image caption box misdetected
    as a table by PyMuPDF.

    These tables contain no real data — every cell is either empty, a lone '.',
    or an image caption ID (matching IMAGE_ID_RE).  At least one cell must be
    an image ID for the test to fire (prevents matching a genuinely empty table).

    The corresponding image is already captured in images[] with the correct
    caption, so discarding the table loses nothing.
    """
    has_image_id = False
    for row in rows:
        for cell in row:
            val = str(cell).strip() if cell is not None else ''
            if val == '' or val == '.':
                continue
            if IMAGE_ID_RE.match(val):
                has_image_id = True
            else:
                return False   # real content found — not an image box
    return has_image_id


def read_page_ref(page: fitz.Page) -> str | None:
    """
    Extract the printed page label from the page footer (e.g. 'EVB-88').
    Clips the bottom 12% of the page where the footer label lives.
    Returns None if no label is found.
    """
    rect = page.rect
    footer_rect = fitz.Rect(0, rect.height * 0.88, rect.width, rect.height)
    footer_text = page.get_text("text", clip=footer_rect)
    match = _PAGE_REF_RE.search(footer_text)
    return match.group(1) if match else None


def clean_text(raw: str, section_code: str | None = None) -> str:
    """
    Clean extracted zone text:
      1. Strip OEM content IDs (e.g. INFOID:…)
      2. Strip single-letter sidebar tab characters
      3. Repair soft hyphens split across lines ("de-\ntects" → "detects")
      4. Remove standalone noise lines (page refs, revision lines, model names, DTC title headers)
      5. Remove standalone section code sidebar tabs (e.g. "EVB" on its own line)
      6. Collapse excess blank lines
    """
    text = INFOID_RE.sub("", raw)
    text = SIDEBAR_RE.sub("", text)
    # Repair word-break hyphens: only when a word ends with "-" and the
    # next line starts with a letter (upper or lower). The newline is the
    # distinguishing signal — real compounds like LI-ION never contain \n.
    text = re.sub(r"(\w+)-\n([A-Za-z])", r"\1\2", text)
    # Drop lines that are pure header/footer noise (page refs, revision, model name, DTC title).
    lines = [ln for ln in text.split("\n") if not is_noise(ln)]
    # Drop standalone section code sidebar tabs (e.g. "EVB" from page continuation header).
    if section_code:
        lines = [ln for ln in lines if ln.strip() != section_code]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def page_belongs_to_codes(page: fitz.Page, codes: list) -> bool:
    """
    Check if a page header contains any of the given codes.
    We only check the first 300 characters — the header area.
    """
    top_text = page.get_text("text")[:300].upper()
    return any(code.upper() in top_text for code in codes)


def _find_heading_y(page: fitz.Page, heading: str) -> tuple[float, float] | None:
    """
    Find the y-coordinates of a heading line on a page.
    Searches every line in every block using normalised matching:
      - case-insensitive
      - internal whitespace runs collapsed to a single space
    Returns (y_top, y_bottom) so callers can:
      - end the previous zone at y_top  (before the heading text)
      - start the new zone at y_bottom  (after the heading text)
    Returns None if not found.
    """
    target = normalize_heading(heading)
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:   # text blocks only
            continue
        for line in block.get("lines", []):
            line_text = normalize_heading(
                " ".join(span["text"] for span in line.get("spans", []))
            )
            if line_text == target:
                return line["bbox"][1], line["bbox"][3]  # (y_top, y_bottom)
    return None


_STRUCTURAL_HEADING_EXCLUDES = [
    # Safety callout labels — bold by design but not DTC section headings
    re.compile(r'^(CAUTION|WARNING|DANGER|NOTE|IMPORTANT)\s*:?\s*$', re.IGNORECASE),
    # Labels ending in colon — sub-labels inside content (e.g. "Value:", "Reference:")
    re.compile(r'^[A-Za-z ]{1,20}:\s*$'),
    # Lines starting with colon — terminal/component labels e.g. ": Negative terminal (Black)"
    re.compile(r'^:'),
    # Lines that start with lowercase — continuation of a hyphenated word, not a heading
    re.compile(r'^[a-z]'),
    # Bullet point lines — bold step instructions, never section headings
    re.compile(r'^[•\-–—]'),
    # DTC code range titles printed at page tops: "P3031-P303C CELL CONTROLLER ASIC"
    re.compile(r'^[PBCU][0-9A-F]{4}[-–][PBCU][0-9A-F]{4}', re.IGNORECASE),
    # Single DTC code + any title text: "P30E4 DLC DIAGNOSIS PDM(...)", "P31A7 CAN ERROR INV/MC"
    # These are record-title continuation headers, not section headings
    re.compile(r'^[PBCU][0-9A-F]{4}\s+\S', re.IGNORECASE),
    # Multi-code comma titles: "P33D7, P33D9, P33DD TEMPERATURE SENSOR"
    re.compile(r'^[PBCU][0-9A-F]{4},', re.IGNORECASE),
    # Lines that look like sentences (long lines ending with period/comma, any case)
    # e.g. "Disconnect the high voltage circuit before working."
    re.compile(r'.{30,}[.,]$'),
    # Short sentence instructions — bold numbered step body text, too short for the above.
    # Contains lowercase (so it's a sentence, not an ALL-CAPS title) and ends with . or )
    # e.g. "Stop the vehicle.", "Never depress brake pedal.", "3 minutes or more. (...)"
    re.compile(r'.*[a-z].*[.)]$'),
    # Cross-reference link text ending with " . — Nissan hyperlink format.
    # e.g. 'EVC-114, "DTC Logic" .'  or truncated fragment  'DURE" .'
    re.compile(r'"\s*\.\s*$'),
    # Sub-procedure tool labels: "With CONSULT", "With CONSULT-III"
    # Bold labels marking which tool path to follow inside a procedure step — not headings.
    re.compile(r'^With\s+', re.IGNORECASE),
    # DTC code immediately followed by period: "P31CA. P31CB QUICK CHARGE RELAY"
    # Multi-code page titles that use a period separator instead of a space or comma.
    re.compile(r'^[PBCU][0-9A-F]{4}\.', re.IGNORECASE),
    # Bracketed labels: "[TYPE 1]", "[AUTOMATIC AIR CONDITIONER]", "[TELEMATICS SYSTEM]"
    # These are variant/subsystem/applicability markers preserved in raw_text — not section headings.
    re.compile(r'^\[.*\]$'),
    # Lines ending with common function words — wrapped sentence fragments, not headings.
    # e.g. "Touching high voltage components without using the"
    re.compile(r'\b(the|a|an|of|with|using|for|to|in|on|at|by|from|and|or|but|if|that|which|this|these)\s*$', re.IGNORECASE),
]


def _find_structural_headings(page: fitz.Page) -> list[dict]:
    """
    Scan all text lines on a page for lines that look structurally like headings
    but are NOT in HEADING_LOOKUP.

    A line is a candidate heading when ALL of these are true:
      - Bold font (span flags & 16 — the bold bit in PDF font flags)
      - Short text: <= 80 characters (headings are titles, not paragraphs)
      - Not a noise line (page ref, revision, model name, DTC title header)
      - Not a safety callout label (CAUTION:, WARNING:, DANGER: etc.)
      - Not a sentence continuation (starts lowercase, or ends with punctuation + is long)
      - Not already matched by HEADING_LOOKUP

    Returns a list of dicts — one per unknown candidate:
      {
        "text":   str,    # raw heading text as found on the page
        "y_top":  float,  # top of the line bounding box
        "y_bot":  float,  # bottom of the line bounding box
      }

    Called once per page in the section-detection loop.
    Its output is written to a per-record warning so developers know
    exactly which headings need to be added to KNOWN_HEADINGS.
    """
    candidates = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue

            # Collect text and check if every span is bold (flag bit 16 = bold)
            text = " ".join(s["text"] for s in spans).strip()
            all_bold = all(bool(s.get("flags", 0) & 16) for s in spans)

            if not all_bold:
                continue
            if len(text) > 55:
                continue
            if len(text.split()) < 2:
                continue
            if is_noise(text):
                continue

            # Apply exclusion patterns — filters safety callouts, labels, sentences
            if any(p.search(text) for p in _STRUCTURAL_HEADING_EXCLUDES):
                continue

            key = normalize_heading(text)
            if not key:
                continue
            if key in HEADING_LOOKUP:
                continue   # already handled — not unknown

            candidates.append({
                "text":  text,
                "y_top": line["bbox"][1],
                "y_bot": line["bbox"][3],
            })

    return candidates


def _get_line_extent(page: fitz.Page, table_bbox: tuple) -> tuple[float, float]:
    """
    Scan drawing paths for horizontal lines that overlap the table's y-range.
    Returns (left_x, right_x) — the widest span found.
    Falls back to the table bbox edges if no wider lines are found.

    A horizontal line is a filled rect that is very short in height (<=3 pt)
    and meaningfully wide (>=20 pt).
    """
    ty0, ty1 = table_bbox[1], table_bbox[3]
    left_x  = table_bbox[0]
    right_x = table_bbox[2]

    for path in page.get_drawings():
        r = path.get("rect")
        if r is None:
            continue
        height = r.y1 - r.y0
        width  = r.x1 - r.x0
        if height > 3 or width < 20:   # not a horizontal rule
            continue
        if r.y0 < ty1 and r.y1 > ty0:  # overlaps table y-range
            left_x  = min(left_x,  r.x0)
            right_x = max(right_x, r.x1)

    return left_x, right_x


def _drawn_table_rect(page: fitz.Page, table_bbox: tuple) -> "fitz.Rect | None":
    """
    Derive the true table bounding rect from drawn border rectangles.

    Used as a fallback when find_tables() returns a bbox that extends to the
    full page width — a known PyMuPDF failure mode when the right vertical
    border line is absent or very thin.

    A table border is a thin (height <= 3 pt), wide (width >= 20 pt) filled
    or stroked near-black rectangle whose right edge does not touch the page
    margin (x1 < page_width - 5).  At least two such borders must agree
    before a corrected rect is returned.

    Returns corrected fitz.Rect (possibly narrower and/or with a higher y0
    than the original bbox), or None if not enough borders are found.
    """
    pw  = page.rect.width
    ty0 = table_bbox[1]
    ty1 = table_bbox[3]
    margin = 20   # search a little above/below the bbox to catch border lines

    h_borders = []
    for path in page.get_drawings():
        r = path.get("rect")
        if r is None:
            continue
        # Must overlap the expanded y-search zone
        if r.y1 < ty0 - margin or r.y0 > ty1 + margin:
            continue
        height = r.y1 - r.y0
        width  = r.x1 - r.x0
        # Horizontal border: thin, meaningfully wide, not a page-wide rule
        if height > 3 or width < 20:
            continue
        if r.x1 >= pw - 5:   # skip rules that reach the page right edge
            continue
        # Must have a near-black fill or stroke colour.
        # PyMuPDF colors: grayscale = float, RGB = (r,g,b), CMYK = (c,m,y,k).
        fill  = path.get("fill")
        color = path.get("color")
        ref   = fill if fill is not None else color
        if ref is None:
            continue
        if isinstance(ref, (int, float)):
            if ref >= 0.3:   # grayscale: 0.0 = black, 1.0 = white
                continue
        elif not all(ch < 0.3 for ch in ref[:3]):
            continue
        h_borders.append(r)

    if len(h_borders) < 2:
        return None

    true_x0 = min(r.x0 for r in h_borders)
    true_x1 = max(r.x1 for r in h_borders)
    true_y0 = min(r.y0 for r in h_borders)
    true_y1 = max(r.y1 for r in h_borders)

    return fitz.Rect(true_x0, true_y0, true_x1, true_y1)


def _row_y_ranges(table) -> list[tuple[float, float]]:
    """
    Derive per-row y-ranges from the table's cell bounding boxes.
    Works for any table regardless of row count or row height.
    """
    y_vals = set()
    for cell in table.cells:
        y_vals.add(cell[1])   # y0
        y_vals.add(cell[3])   # y1
    y_sorted = sorted(y_vals)
    return [(y_sorted[i], y_sorted[i + 1]) for i in range(len(y_sorted) - 1)]


def _bbox_rebuild_table(page: fitz.Page, table_rect: fitz.Rect) -> list[list[str]]:
    """
    Reconstruct table rows using word-level X/Y positions.

    Used as a repair fallback when find_tables() drops outer columns due to
    absent vertical border lines or merged cells spanning the table edge.

    Generic across manufacturers and PDF layouts — no hardcoded column names
    or fixed pixel assumptions.  All thresholds are derived from the actual
    word geometry of the table being processed.

    Algorithm:
      1. Collect all words in table_rect via page.get_text("words").
      2. Cluster words into rows by Y-centre (ROW_TOL = 40% of median word height).
      3. Within each row, merge adjacent words into cell tokens (gap <= WORD_GAP pt).
      4. Cluster token X0 positions into column starts (X0_TOL = 5 pt within-column
         tolerance).  Rounding to 1 pt before clustering absorbs PDF sub-pixel noise.
      5. Assign each token to its nearest column start; build cell strings.
      6. Drop columns present in fewer than 20% of rows (sidebar letters, page
         numbers, other per-page noise outside the real table body).

    Returns [] when the rect yields fewer than 2 rows or fewer than 2 valid
    columns after the fill filter — caller keeps original clean_rows.
    """
    words = page.get_text("words", clip=table_rect)
    if not words:
        return []

    WORD_GAP = 8    # pt — intra-cell word spacing; stable across font sizes
    X0_TOL   = 5    # pt — within-column X0 clustering tolerance

    # ROW_TOL derived from median word height so clustering adapts to font size.
    # 40% of word height handles multi-word cells without merging adjacent rows.
    word_heights = [w[3] - w[1] for w in words if w[3] > w[1]]
    median_h     = sorted(word_heights)[len(word_heights) // 2] if word_heights else 10.0
    ROW_TOL      = max(2.0, median_h * 0.4)

    # ── 1. Cluster words into rows by Y centre ────────────────────────────
    rows_raw: list[list] = []
    for w in sorted(words, key=lambda w: w[1]):        # top-to-bottom by y0
        yc = (w[1] + w[3]) / 2
        if rows_raw:
            last_yc = sum((x[1] + x[3]) / 2 for x in rows_raw[-1]) / len(rows_raw[-1])
            if abs(yc - last_yc) <= ROW_TOL:
                rows_raw[-1].append(w)
                continue
        rows_raw.append([w])

    if len(rows_raw) < 2:
        return []

    # ── 2. Merge adjacent words → cell tokens ─────────────────────────────
    # Each token stored as (x0, x1, text).
    token_rows: list[list[tuple]] = []
    for row in rows_raw:
        row.sort(key=lambda w: w[0])                   # left-to-right by x0
        tokens: list[tuple] = []
        for w in row:
            x0, x1, text = w[0], w[2], w[4]
            if tokens and x0 - tokens[-1][1] <= WORD_GAP:
                tokens[-1] = (tokens[-1][0], x1, tokens[-1][2] + ' ' + text)
            else:
                tokens.append((x0, x1, text))
        token_rows.append(tokens)

    # ── 3. Derive column start positions from all token X0 values ─────────
    # Round to 1 pt first to absorb PDF sub-pixel variation within a column.
    # Then cluster rounded X0 values: positions within X0_TOL pt belong to
    # the same column.  Columns only a few pt apart are still separated;
    # within-column X0 drift (< 3 pt in practice) is correctly merged.
    all_x0 = sorted({round(t[0]) for row in token_rows for t in row})
    col_starts: list[float] = []
    for x in all_x0:
        if not col_starts or x - col_starts[-1] >= X0_TOL:
            col_starts.append(float(x))

    if not col_starts:
        return []

    n_cols = len(col_starts)

    # ── 4. Assign tokens to columns ───────────────────────────────────────
    result: list[list[str]] = []
    for tokens in token_rows:
        cells = [''] * n_cols
        for t in tokens:
            col_idx = min(range(n_cols), key=lambda i: abs(t[0] - col_starts[i]))
            cells[col_idx] = (cells[col_idx] + ' ' + t[2]).strip() if cells[col_idx] else t[2]
        result.append(cells)

    # ── 5. Drop spurious columns ──────────────────────────────────────────
    # A real column has content in at least 20% of rows.  Columns below that
    # threshold are sidebar letters, page numbers, or other per-page noise
    # that happens to fall inside the repair rect.
    # Require content in at least 2 rows AND 25% of rows.
    # max(1, 20%) degenerates to 1 for small tables — any column with a single
    # populated row survives, including phantom separator columns from X0 drift.
    min_presence = max(2, round(len(result) * 0.25))
    valid_idxs   = [i for i in range(n_cols)
                    if sum(1 for row in result if row[i]) >= min_presence]
    if len(valid_idxs) < 2:
        return []
    if len(valid_idxs) < n_cols:
        result  = [[row[i] for i in valid_idxs] for row in result]
        n_cols  = len(valid_idxs)   # noqa: F841 — kept for clarity

    return result


def _dedup_merged_cells(rows: list[list[str]]) -> list[list[str]]:
    """
    Collapse repeated consecutive values in each column.

    PDF tables with merged cells produce duplicate text because
    _bbox_rebuild_table() sees the merged cell content once per
    logical row line:

        ["P3373", "DISCHARGE", "voltage range.", "• Service plug fuse"]
        ["P3373", "DISCHARGE", "voltage range.", "• Overcharge..."]
        ["P3373", "DISCHARGE", "voltage range.", "• Harness or connector"]

    After dedup — first occurrence kept, subsequent repeats cleared:

        ["P3373", "DISCHARGE", "voltage range.", "• Service plug fuse"]
        ["",      "",          "",               "• Overcharge..."]
        ["",      "",          "",               "• Harness or connector"]

    Empty strings are never treated as duplicates — only non-empty
    repeated values are cleared.
    """
    if not rows:
        return rows
    n_cols = max(len(row) for row in rows)
    prev   = [None] * n_cols
    result = []
    for row in rows:
        new_row = []
        for i in range(n_cols):
            val = row[i] if i < len(row) else ""
            if val and val == prev[i]:
                new_row.append("")
            else:
                new_row.append(val)
                prev[i] = val if val else prev[i]
        result.append(new_row)
    return result


def extract_tables_from_rect(page: fitz.Page, rect: fitz.Rect) -> list:
    """
    Extract tables whose bounding box overlaps rect by at least 50%.

    Returns list of table dicts:
        {
            "rows":       list[list[str]],   # cells preserve internal newlines
            "extraction": {
                "confidence":    "high" | "medium" | "low",
                "quality_flags": list[str]   # traceable structural signals
            }
        }

    No table content is silently discarded.  Tables that would previously
    have been skipped (< 2 rows, < 2 cols, blob rows, short outer-column
    tokens) are kept and flagged instead.

    Confidence model — conservative, lowest signal wins:
        Start at "high".
        Medium signals (bbox_reconstruction_used, outer_column_recovered)
            → downgrade to "medium".
        Low signals (blob_row_detected, single_row_table, single_column_table)
            → downgrade to "low".

    Handles tables whose outermost columns have no vertical border line:
    fitz misses those columns because it uses drawn vertical lines as column
    boundaries. We recover them by checking whether the page's horizontal
    rules extend beyond the detected table bbox and, if so, extracting text
    from those outer zones per row.
    """
    if rect is None or rect.is_empty:
        return []

    finder = page.find_tables()
    result = []

    for table in finder.tables:
        tbbox      = fitz.Rect(table.bbox)
        overlap    = rect & tbbox
        if overlap.is_empty:
            continue

        table_area = tbbox.width * tbbox.height
        if table_area == 0:
            continue

        overlap_ratio = (overlap.width * overlap.height) / table_area
        if overlap_ratio < 0.5:
            continue

        rows = table.extract()
        if not rows:
            continue

        quality_flags: list[str] = []

        # Flag instead of discard: single-row / single-column tables are kept
        # for traceability — they are likely noise or continuation fragments.
        if len(rows) < 2:
            quality_flags.append("single_row_table")
        if rows[0] and len(rows[0]) < 2:
            quality_flags.append("single_column_table")

        # Detect blob row BEFORE normalisation (newlines still present in raw).
        # fitz sometimes dumps all continuation text into cell[0][0] with all
        # other cells empty.  Flag and keep — do not strip.
        if (len(rows) > 1
                and rows[0] is not None
                and rows[0][0] is not None
                and '\n' in str(rows[0][0])
                and all((c is None or c == '') for c in rows[0][1:])):
            quality_flags.append("blob_row_detected")

        # Normalise cells: None → ""; collapse intra-line spaces; preserve
        # newlines so multi-line cell content reaches the importer intact.
        clean_rows = [
            [
                "\n".join(" ".join(ln.split()) for ln in str(cell).split("\n")).strip()
                if cell is not None else ""
                for cell in row
            ]
            for row in rows
        ]

        # Recover columns hidden outside the detected table bbox.
        # Always prepend/append recovered content — no token-length filter.
        # Callers can identify recovered columns via the quality flag.
        line_left, line_right = _get_line_extent(page, table.bbox)
        row_ranges = _row_y_ranges(table)
        outer_col_recovered = False


        if table.bbox[0] - line_left > 5:
            col = []
            for ry0, ry1 in row_ranges:
                # Use word-level extraction and select by word x0, not by
                # character clip.  A word like "LBC" whose x0 is in the outer
                # zone but whose x1 crosses the table edge is correctly included
                # here; character-clip mode would truncate it to "LB".
                all_words = page.get_text("words", clip=fitz.Rect(line_left, ry0, table.bbox[2], ry1))
                outer = sorted([w for w in all_words if w[0] < table.bbox[0]], key=lambda w: (w[1], w[0]))
                col.append(" ".join(w[4] for w in outer))
            for r_idx, v in enumerate(col):
                clean_rows[r_idx].insert(0, v)
            outer_col_recovered = True

        if line_right - table.bbox[2] > 5:
            col = []
            for ry0, ry1 in row_ranges:
                # Symmetric: select words whose x0 starts in the outer right
                # zone (at or beyond the table's right edge).
                all_words = page.get_text("words", clip=fitz.Rect(table.bbox[0], ry0, line_right, ry1))
                outer = sorted([w for w in all_words if w[0] >= table.bbox[2]], key=lambda w: (w[1], w[0]))
                col.append(" ".join(w[4] for w in outer))
            # Discard column if every non-empty value is a sidebar tab:
            # a single uppercase letter (A, B…) or short section code (EVB).
            # These are page navigation tabs, not table data.
            non_empty = [v for v in col if v.strip()]
            if non_empty and not all(_SIDEBAR_VAL_RE.match(v.strip()) for v in non_empty):
                for r_idx, v in enumerate(col):
                    clean_rows[r_idx].append(v)
                outer_col_recovered = True

        if outer_col_recovered:
            quality_flags.append("outer_column_recovered")

        # ── Bbox repair pass ──────────────────────────────────────────────────
        # Word-position reconstruction over the horizontal rule extent.
        #
        # Two cases:
        #
        # A) find_tables() bbox extends to the full page right edge — a known
        #    PyMuPDF failure when the right vertical border line is absent.
        #    We read drawn border rectangles to derive the true table rect
        #    (narrower x1, and a y0 that skips prose text above the real top
        #    border).  When the drawn rect is found we ALWAYS prefer it.
        #
        # B) Normal case — only replace clean_rows when the reconstruction
        #    finds more columns AND fill confidence is sufficient.
        pw_local = page.rect.width
        drawn_rect = None
        if tbbox.x1 >= pw_local - 5:
            drawn_rect = _drawn_table_rect(page, table.bbox)
            if drawn_rect and drawn_rect.x1 < tbbox.x1 - 5:
                repair_rect = drawn_rect
                quality_flags.append("bbox_clipped_by_drawings")
            else:
                drawn_rect  = None   # no useful correction found
                quality_flags.append("wide_bbox_uncorrected")
                repair_rect = fitz.Rect(line_left, tbbox.y0, line_right, tbbox.y1)
        else:
            repair_rect = fitz.Rect(line_left, tbbox.y0, line_right, tbbox.y1)

        bbox_rows    = _bbox_rebuild_table(page, repair_rect)
        use_bbox_rows = False
        if bbox_rows and clean_rows:
            if drawn_rect is not None:
                # Case A: bbox was wrong — always use the drawing-derived result
                use_bbox_rows = True
            elif len(bbox_rows[0]) > len(clean_rows[0]):
                # Case B: only prefer reconstruction when it finds more columns.
                # Reject when bbox column count exceeds find_tables() by more than
                # 1.5× — heavy inflation is a reliable signal of phantom columns
                # caused by centered header text vs left-aligned data X0 drift.
                col_ratio = len(bbox_rows[0]) / len(clean_rows[0])
                if col_ratio <= 1.5:
                    min_filled = max(1, len(bbox_rows[0]) // 2)
                    good_rows  = sum(1 for row in bbox_rows
                                     if sum(1 for c in row if c) >= min_filled)
                    use_bbox_rows = good_rows / len(bbox_rows) >= 0.5

        if use_bbox_rows:
            clean_rows = [
                [
                    "\n".join(" ".join(ln.split()) for ln in c.split("\n")).strip()
                    for c in row
                ]
                for row in bbox_rows
            ]
            quality_flags.append("bbox_reconstruction_used")

        # ── Cleaned rows — layout newlines removed ───────────────────────────────
        # Derived from the final clean_rows:
        #   1. Repair soft hyphens split by PDF line wrap ("ENGAGE-\nMENT" → "ENGAGEMENT")
        #   2. Replace remaining layout newlines with a space
        #   3. Collapse any resulting double spaces
        def _clean_cell(cell: str) -> str:
            cell = re.sub(r'(\w+)-\n([A-Za-z])', r'\1\2', cell)  # de-hyphenation
            cell = cell.replace('\n', ' ')                      # join layout newlines
            return ' '.join(cell.split())                       # collapse spaces

        # Blob rows (blob_row_detected) contain the entire table as a single text
        # dump — their newlines are structural, not layout artifacts.  Leave the
        # blob row untouched; clean only the structured rows that follow it.
        if "blob_row_detected" in quality_flags and clean_rows:
            cleaned_rows = [list(clean_rows[0])] + [
                [_clean_cell(cell) for cell in row] for row in clean_rows[1:]
            ]
        else:
            cleaned_rows = [[_clean_cell(cell) for cell in row] for row in clean_rows]

        # ── Confidence: conservative — lowest signal wins ─────────────────────
        # Start at "high". Any low signal → "low". Any medium signal → "medium".
        # If both are present the low signal wins.
        LOW_SIGNALS    = {"blob_row_detected", "single_row_table", "single_column_table"}
        MEDIUM_SIGNALS = {"bbox_reconstruction_used", "outer_column_recovered", "bbox_clipped_by_drawings", "wide_bbox_uncorrected"}
        flag_set = set(quality_flags)
        if flag_set & LOW_SIGNALS:
            confidence = "low"
        elif flag_set & MEDIUM_SIGNALS:
            confidence = "medium"
        else:
            confidence = "high"

        # ── Image-box filter ──────────────────────────────────────────────────
        # PyMuPDF sometimes detects wiring-diagram caption boxes as tables.
        # These contain only empty cells, dots, and an image caption ID.
        # The image is already captured in images[] — discard the false table.
        if _is_image_box_table(clean_rows):
            continue

        result.append({
            "rows":         clean_rows,   # raw: internal newlines preserved
            "cleaned_rows": cleaned_rows, # cleaned: newlines joined, hyphens repaired
            "extraction": {
                "confidence":    confidence,
                "quality_flags": quality_flags,
            },
        })

    return result


def _clean_zone_text(page: fitz.Page, rect: fitz.Rect, section_code: str | None = None) -> str:
    """Extract and clean all text from a zone rect on a page."""
    raw = page.get_text("text", clip=rect)
    return clean_text(raw, section_code)


def _extract_oem_content_id(page: fitz.Page, rect: fitz.Rect) -> str | None:
    """
    Extract the OEM-assigned content identifier from a zone rect.

    Nissan uses 'INFOID:0000000005277155' — a unique ID per subsection printed
    by their authoring system.  Other OEMs may use different formats; the regex
    in patterns.py controls what is matched.

    Returns the full identifier string (e.g. 'INFOID:0000000005277155'), or
    None if no identifier is found.  The identifier is automatically stripped
    from section text by clean_text(), so no further action is needed there.
    """
    raw = page.get_text("text", clip=rect)
    match = INFOID_RE.search(raw)
    return match.group(0) if match else None


def _get_table_bboxes_in_zone(page: fitz.Page, rect: fitz.Rect) -> list:
    """
    Return fitz.Rect bboxes of all tables whose area overlaps rect by >= 50%.
    Used to build the exclude_rects list for _clean_zone_text.
    """
    bboxes = []
    try:
        for table in page.find_tables().tables:
            tbbox = fitz.Rect(table.bbox)
            overlap = rect & tbbox
            if overlap.is_empty:
                continue
            table_area = tbbox.get_area()
            if table_area > 0 and overlap.get_area() / table_area >= 0.5:
                bboxes.append(tbbox)
    except Exception:
        pass
    return bboxes


def _finalize_section(section: dict) -> dict:
    """
    Convert the internal section builder into the final section dict.
    Joins text collected across multiple pages into one string.
    """
    return {
        "heading":          section["heading"],
        "role":             section["role"],
        "oem_content_id":   section.get("oem_content_id"),
        # cleaned text: noise filtered, soft hyphens repaired, sidebar tabs removed
        "cleaned_text":     "\n\n".join(section["text_parts"]).strip() or None,
        # raw text: uncleaned zone text preserved for importer / debug use
        "raw_text":         "\n\n".join(section.get("raw_text_parts", [])).strip() or None,
        "tables":           section["tables"],   # list of {page, page_ref, rows, extraction}
        "page_start":       section["page_start"],
        "page_end":         section["page_end"],
    }


def _find_image_caption(page: fitz.Page, xref: int) -> str | None:
    """
    Look for a short identifier/caption in the text immediately below the image.

    Works generically — matches any short uppercase alphanumeric code
    (e.g. JSCIA0812GB, JPCIA0347ZZ) within 60pt below the image bbox.
    Returns the identifier string, or None if nothing found.
    """
    rects = page.get_image_rects(xref)
    if not rects:
        return None

    bbox = rects[0]

    for block in page.get_text("dict")["blocks"]:
        if block["type"] != 0:
            continue
        bx = block["bbox"]
        # Look within 40pt above the image bottom (catches identifiers
        # printed inside the bottom of the image area) and 60pt below it.
        if bx[1] < bbox.y1 - 40 or bx[1] > bbox.y1 + 60:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                text = span["text"].strip()
                if IMAGE_ID_RE.match(text):
                    return text
    return None


def extract_content(
    pdf: fitz.Document,
    start_page: int,
    codes: list,
    output_dir: Path,      # folder where image files will be saved
    page_ref_base: str,    # e.g. "EVB-167" — used as the image filename prefix
    seen_xrefs: set,       # shared across all sections — prevents saving same xref twice
    seen_hashes: dict,     # hash → filename — points duplicates to the already-saved file
    page_type_map: dict | None = None,  # {pdf_page: "TYPE N" | None} from type_detector
) -> dict:
    """
    Extract content starting from start_page, continuing while
    the page header still belongs to our codes.

    pdf is an already-open fitz.Document — the caller owns it and keeps it open
    across all extract_content calls for the same PDF.

    Returns:
        sections                 — list of section dicts with text, raw_text, tables, page range
        has_images               — True if any images were saved
        image_list               — list of image metadata dicts (filename, pdf_page, page_ref)
        page_refs                — ordered list of all footer page labels seen (full span)
        start_page_ref_footer    — footer label on first page (for cross-check in extractor)
        end_page_ref             — footer label on last page (for cross-check in extractor)
        end_pdf_page             — physical PDF page of last page (1-indexed)
    """
    total_pages = len(pdf)

    has_images            = False
    image_list            = []   # image metadata, IDs assigned later in extractor.py
    image_warnings        = []   # one entry per failed image: xref + page + reason
    img_counter           = 1
    all_page_refs         = []   # ordered footer labels for every page in this block
    start_page_ref_footer = None
    end_page_ref          = None
    last_processed           = start_page
    start_section_code       = None   # e.g. "EVB" from "EVB-88"
    start_manual_type        = page_type_map.get(start_page) if page_type_map else None
    stopped_at_type_boundary = False  # set True when TYPE changes mid-block

    # ── Section tracking ──────────────────────────────────────────────────
    # active_section holds the section currently being built.
    # When a new heading is found, we close active_section and open a new one.
    active_section = None
    all_sections   = []

    # ── Unknown heading tracking ──────────────────────────────────────────
    # Collects bold/short lines found on any page in this record that are NOT
    # in HEADING_LOOKUP. Surfaced in the returned warnings list so the caller
    # can log them and developers know what to add to KNOWN_HEADINGS.
    unknown_headings_this_record: set[str] = set()

    for page_num in range(start_page, total_pages + 1):
        page = pdf[page_num - 1]

        if page_num > start_page and not page_belongs_to_codes(page, codes):
            break

        # ── Footer page label ─────────────────────────────────────────────
        ref = read_page_ref(page)

        # ── Section boundary check ────────────────────────────────────────
        # Stop when the page-ref prefix changes (e.g. EVB → EVC).
        # Protects against cross-section merging in merged PDFs.
        if page_num == start_page:
            start_page_ref_footer = ref
            if ref:
                start_section_code = ref.split('-')[0]
        elif start_section_code and ref:
            current_section = ref.split('-')[0]
            if current_section != start_section_code:
                print(f"  [WARN section-boundary] stopped at PDF page {page_num}: "
                      f"section changed {start_section_code!r} → {current_section!r}")
                break

        # ── Manual TYPE boundary check ────────────────────────────────────
        # Stop when the manual_type changes (e.g. TYPE 1 → TYPE 2).
        # Acts as a split point — the caller restarts extraction from this
        # page as a new record under the new manual_type (no pages dropped).
        if page_type_map is not None and page_num != start_page:
            page_manual_type = page_type_map.get(page_num)
            if page_manual_type != start_manual_type:
                print(f"  [INFO type-boundary] split at PDF page {page_num}: "
                      f"manual_type {start_manual_type!r} → {page_manual_type!r}")
                stopped_at_type_boundary = True
                break

        last_processed = page_num
        end_page_ref = ref
        if ref and ref not in all_page_refs:
            all_page_refs.append(ref)

        pw = page.rect.width
        ph = page.rect.height

        # ── Images ────────────────────────────────────────────────────────
        for img_info in page.get_images(full=True):
            xref = img_info[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)

            try:
                img_data = pdf.extract_image(xref)
                if img_data["width"] < 500 or img_data["height"] < 500:
                    continue

                img_bytes    = img_data["image"]
                img_ext      = img_data["ext"]
                img_hash     = hashlib.md5(img_bytes).hexdigest()
                img_filename = f"{ref or page_ref_base}-img{img_counter}.{img_ext}"
                img_path     = output_dir / img_filename

                if img_hash not in seen_hashes:
                    with open(img_path, "wb") as f:
                        f.write(img_bytes)
                    seen_hashes[img_hash] = img_filename

                # Store metadata — image_id is assigned later in extractor.py
                image_list.append({
                    "filename": seen_hashes[img_hash],
                    "pdf_page": page_num,
                    "page_ref": ref,
                    "caption":  _find_image_caption(page, xref),
                })
                img_counter += 1
                has_images = True

            except Exception as e:
                msg = f"skipped image xref={xref} on page {ref or page_num}: {e}"
                print(f"  [WARN] {msg}")
                image_warnings.append(msg)

        # ── Section detection ─────────────────────────────────────────────
        # Find all known headings on this page and sort them top-to-bottom.
        # Each entry: (y_top, y_bottom, display_name, role)
        # y_top  — used to END the previous zone (stops before heading text)
        # y_bottom — used to START this zone (starts after heading text)
        breaks = []
        for display_name, role in KNOWN_HEADINGS:
            result = _find_heading_y(page, display_name)
            if result is not None:
                y_top, y_bottom = result
                breaks.append((y_top, y_bottom, display_name, role))
        breaks.sort(key=lambda x: x[0])

        # ── Unknown heading detection ──────────────────────────────────────
        # Find structurally bold/short lines on this page that are NOT in
        # HEADING_LOOKUP. Collect them per-record so they appear in warnings[].
        # These tell you exactly which headings need to be added to KNOWN_HEADINGS
        # to support a new manufacturer — zero guesswork needed.
        unknown_heads = _find_structural_headings(page)
        for uh in unknown_heads:
            unknown_headings_this_record.add(uh["text"])

        if not breaks:
            # No headings on this page — entire page continues active section
            if active_section is not None:
                page_rect    = fitz.Rect(0, 0, pw, ph)
                section_code = ref.split('-')[0] if ref else None
                text    = _clean_zone_text(page, page_rect, section_code)
                raw_txt = page.get_text("text", clip=page_rect)
                if text:
                    active_section["text_parts"].append(text)
                if raw_txt.strip():
                    active_section["raw_text_parts"].append(raw_txt)
                for td in extract_tables_from_rect(page, page_rect):
                    active_section["tables"].append({
                        "page":         page_num,
                        "page_ref":     ref,
                        "rows":         td["rows"],
                        "cleaned_rows": td["cleaned_rows"],
                        "extraction":   td["extraction"],
                    })
                active_section["page_end"] = page_num

        else:
            # ── Content before the first heading ─────────────────────────
            # Belongs to the active section (continuation from a previous page).
            # Clip to y_top so the heading text itself is excluded.
            first_y_top  = breaks[0][0]
            section_code = ref.split('-')[0] if ref else None
            if first_y_top > 0 and active_section is not None:
                pre_rect = fitz.Rect(0, 0, pw, first_y_top)
                pre_text = _clean_zone_text(page, pre_rect, section_code)
                pre_raw  = page.get_text("text", clip=pre_rect)
                if pre_text:
                    active_section["text_parts"].append(pre_text)
                if pre_raw.strip():
                    active_section["raw_text_parts"].append(pre_raw)
                for td in extract_tables_from_rect(page, pre_rect):
                    active_section["tables"].append({
                        "page":         page_num,
                        "page_ref":     ref,
                        "rows":         td["rows"],
                        "cleaned_rows": td["cleaned_rows"],
                        "extraction":   td["extraction"],
                    })
                active_section["page_end"] = page_num

            # ── Process each heading zone ─────────────────────────────────
            for i, (y_top, y_bottom, display_name, role) in enumerate(breaks):
                # Close the section that was active before this heading
                if active_section is not None:
                    all_sections.append(_finalize_section(active_section))

                # Zone runs from y_bottom of this heading to y_top of the
                # next heading (or page bottom).  Using y_top of the next
                # heading means the next heading's text is NOT included here.
                y_end     = breaks[i + 1][0] if i + 1 < len(breaks) else ph
                zone_rect = fitz.Rect(0, y_bottom, pw, y_end)
                zone_text = _clean_zone_text(page, zone_rect, section_code)
                zone_raw  = page.get_text("text", clip=zone_rect)
                # INFOID sits on the same line as the heading (right margin) —
                # it is above zone_rect, so search the heading row itself.
                heading_rect   = fitz.Rect(0, y_top, pw, y_bottom)
                oem_content_id = _extract_oem_content_id(page, heading_rect)
                zone_tables = [
                    {
                        "page":         page_num,
                        "page_ref":     ref,
                        "rows":         td["rows"],
                        "cleaned_rows": td["cleaned_rows"],
                        "extraction":   td["extraction"],
                    }
                    for td in extract_tables_from_rect(page, zone_rect)
                ]

                # Open new section
                active_section = {
                    "heading":         display_name,
                    "role":            role,
                    "oem_content_id":  oem_content_id,
                    "text_parts":      [zone_text] if zone_text else [],
                    "raw_text_parts":  [zone_raw] if zone_raw.strip() else [],
                    "tables":          zone_tables,
                    "page_start":      page_num,
                    "page_end":        page_num,
                }

    # Close the last open section after the page loop ends
    if active_section is not None:
        all_sections.append(_finalize_section(active_section))

    # Build unknown-heading warnings — sorted for stable output
    unknown_heading_warnings = [
        f"unknown heading (not in KNOWN_HEADINGS): {h!r}"
        for h in sorted(unknown_headings_this_record)
    ]

    return {
        "sections":               all_sections,
        "has_images":             has_images,
        "image_list":             image_list,
        "image_warnings":         image_warnings,
        "page_refs":              all_page_refs,
        "start_page_ref_footer":  start_page_ref_footer,
        "end_page_ref":           end_page_ref,
        "end_pdf_page":             last_processed,
        "section_code":             start_section_code,
        "stopped_at_type_boundary": stopped_at_type_boundary,
        "unknown_heading_warnings": unknown_heading_warnings,
    }
