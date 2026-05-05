import re
import hashlib
import fitz
from pathlib import Path
from patterns import INFOID_RE, SIDEBAR_RE, IMAGE_ID_RE
from text_parser import KNOWN_HEADINGS, is_noise

# Matches printed page labels like EVB-88, EVC-109, TM-44, TMS-12
# Pattern: 2–4 uppercase letters, dash, one or more digits
_PAGE_REF_RE = re.compile(r'\b([A-Z]{2,4}-\d+)\b')


def read_page_ref(page: fitz.Page) -> str | None:
    """
    Extract the printed page label from the page footer (e.g. 'EVB-88').
    Clips the bottom 10% of the page where the footer label lives.
    Returns None if no label is found.
    """
    rect = page.rect
    footer_rect = fitz.Rect(0, rect.height * 0.88, rect.width, rect.height)
    footer_text = page.get_text("text", clip=footer_rect)
    match = _PAGE_REF_RE.search(footer_text)
    return match.group(1) if match else None


def clean_text(raw: str) -> str:
    """
    Clean extracted zone text:
      1. Strip OEM content IDs (e.g. INFOID:…)
      2. Strip single-letter sidebar tab characters
      3. Repair soft hyphens split across lines ("de-\ntects" → "detects")
      4. Remove standalone noise lines (page refs, revision lines, model names)
      5. Collapse excess blank lines
    """
    text = INFOID_RE.sub("", raw)
    text = SIDEBAR_RE.sub("", text)
    # Repair word-break hyphens: only when a word ends with "-" and the
    # next line starts with a lowercase letter (soft hyphen, not a real compound).
    text = re.sub(r"(\w+)-\n([a-z])", r"\1\2", text)
    # Drop lines that are pure header/footer noise (page refs, revision, model name).
    lines = [ln for ln in text.split("\n") if not is_noise(ln)]
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
    Searches every line in every block (case-insensitive exact match).
    Returns (y_top, y_bottom) so callers can:
      - end the previous zone at y_top  (before the heading text)
      - start the new zone at y_bottom  (after the heading text)
    Returns None if not found.
    """
    heading_lower = heading.lower()
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:   # text blocks only
            continue
        for line in block.get("lines", []):
            line_text = " ".join(
                span["text"] for span in line.get("spans", [])
            ).strip().lower()
            if line_text == heading_lower:
                return line["bbox"][1], line["bbox"][3]  # (y_top, y_bottom)
    return None


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
    min_presence = max(1, round(len(result) * 0.20))
    valid_idxs   = [i for i in range(n_cols)
                    if sum(1 for row in result if row[i]) >= min_presence]
    if len(valid_idxs) < 2:
        return []
    if len(valid_idxs) < n_cols:
        result  = [[row[i] for i in valid_idxs] for row in result]
        n_cols  = len(valid_idxs)   # noqa: F841 — kept for clarity

    return result


def extract_tables_from_rect(page: fitz.Page, rect: fitz.Rect) -> list:
    """
    Extract tables whose bounding box overlaps rect by at least 50%.

    Returns list of tables.
    Each table  = list of rows.
    Each row    = list of strings (None -> "", whitespace stripped).
    Tables with fewer than 2 rows or 2 columns are skipped (likely noise).

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

        # Skip noise: must have at least 2 rows and 2 columns
        if not rows or len(rows) < 2:
            continue
        if not rows[0] or len(rows[0]) < 2:
            continue

        # Strip blob row BEFORE normalisation (newlines are still present in raw rows).
        # fitz sometimes dumps all continuation text into cell[0][0] (multi-line string)
        # with all other cells empty.  This happens on cross-page tables where the header
        # is reprinted — the rows before the new header have no column boundaries for fitz
        # to split on, so everything ends up in one cell.
        # Condition: first row, first cell contains a newline, all other cells empty/None.
        if (len(rows) > 1
                and rows[0] is not None
                and rows[0][0] is not None
                and '\n' in str(rows[0][0])
                and all((c is None or c == '') for c in rows[0][1:])):
            rows = rows[1:]

        # Normalise cells: None -> "", collapse internal newlines, strip whitespace.
        # Collapsing newlines fixes simple line-break splits that fitz produces
        # when a cell wraps across two printed lines (e.g. "Battery\nvoltage" ->
        # "Battery voltage").
        clean_rows = [
            [" ".join(str(cell).split()) if cell is not None else "" for cell in row]
            for row in rows
        ]

        # Recover columns hidden outside the detected table bbox.
        # Threshold: only act if the extension is more than 5 pt.
        line_left, line_right = _get_line_extent(page, table.bbox)
        row_ranges = _row_y_ranges(table)

        if table.bbox[0] - line_left > 5:
            col = []
            for ry0, ry1 in row_ranges:
                clip = fitz.Rect(line_left, ry0, table.bbox[0], ry1)
                col.append(page.get_text("text", clip=clip).strip())
            # Skip sidebar noise: real content has at least one token > 4 chars.
            # Sidebar letters (A-Z, EVB, etc.) are always 1-3 chars per token.
            if any(len(tok) > 4 for v in col for tok in v.split()):
                for r_idx, v in enumerate(col):
                    clean_rows[r_idx].insert(0, v)

        if line_right - table.bbox[2] > 5:
            col = []
            for ry0, ry1 in row_ranges:
                clip = fitz.Rect(table.bbox[2], ry0, line_right, ry1)
                col.append(page.get_text("text", clip=clip).strip())
            if any(len(tok) > 4 for v in col for tok in v.split()):
                for r_idx, v in enumerate(col):
                    clean_rows[r_idx].append(v)

        # ── Bbox repair pass ──────────────────────────────────────────────────
        # Word-position reconstruction over the full horizontal rule extent.
        # Only replaces clean_rows when:
        #   (a) bbox found more columns than find_tables(), AND
        #   (b) confidence is sufficient: >= 50% of rows have content in at
        #       least half the detected columns.  Low fill means the extra
        #       columns are mostly empty (noise) — keep original in that case.
        repair_rect = fitz.Rect(line_left, tbbox.y0, line_right, tbbox.y1)
        bbox_rows = _bbox_rebuild_table(page, repair_rect)
        if bbox_rows and clean_rows and len(bbox_rows[0]) > len(clean_rows[0]):
            min_filled = max(1, len(bbox_rows[0]) // 2)
            good_rows  = sum(1 for row in bbox_rows
                             if sum(1 for c in row if c) >= min_filled)
            if good_rows / len(bbox_rows) >= 0.5:
                clean_rows = [
                    [" ".join(c.split()) for c in row]
                    for row in bbox_rows
                ]

        result.append(clean_rows)

    return result


def _clean_zone_text(page: fitz.Page, rect: fitz.Rect) -> str:
    """Extract and clean all text from a zone rect on a page."""
    raw = page.get_text("text", clip=rect)
    return clean_text(raw)


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
        # join text collected from multiple pages — None if nothing was collected
        "text":             "\n\n".join(section["text_parts"]).strip() or None,
        "tables":           section["tables"],   # list of {page, page_ref, rows}
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
    pdf_path: Path,
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

    Returns:
        raw_text                 — full unprocessed text across all pages
        sections                 — list of section dicts with text, tables, page range
        has_images               — True if any images were saved
        image_list               — list of image metadata dicts (filename, pdf_page, page_ref)
        page_refs                — ordered list of all footer page labels seen (full span)
        start_page_ref_footer    — footer label on first page (for cross-check in extractor)
        end_page_ref             — footer label on last page (for cross-check in extractor)
        end_pdf_page             — physical PDF page of last page (1-indexed)
    """
    with fitz.open(str(pdf_path)) as pdf:
        total_pages = len(pdf)

        raw_text_parts        = []   # one raw string per page — joined at end
        has_images            = False
        image_list            = []   # image metadata, IDs assigned later in extractor.py
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

            # ── Raw text (unprocessed) ────────────────────────────────────────
            raw_text_parts.append(page.get_text("text"))

            # ── Images ────────────────────────────────────────────────────────
            for img_info in page.get_images(full=True):
                xref = img_info[0]
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)

                img_data = pdf.extract_image(xref)
                if img_data["width"] < 100 or img_data["height"] < 100:
                    continue

                img_bytes    = img_data["image"]
                img_ext      = img_data["ext"]
                img_hash     = hashlib.md5(img_bytes).hexdigest()
                img_filename = f"{page_ref_base}-img{img_counter}.{img_ext}"
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

            if not breaks:
                # No headings on this page — entire page continues active section
                if active_section is not None:
                    page_rect = fitz.Rect(0, 0, pw, ph)
                    text = _clean_zone_text(page, page_rect)
                    if text:
                        active_section["text_parts"].append(text)
                    for rows in extract_tables_from_rect(page, page_rect):
                        active_section["tables"].append({"page": page_num, "page_ref": ref, "rows": rows})
                    active_section["page_end"] = page_num

            else:
                # ── Content before the first heading ─────────────────────────
                # Belongs to the active section (continuation from a previous page).
                # Clip to y_top so the heading text itself is excluded.
                first_y_top = breaks[0][0]
                if first_y_top > 0 and active_section is not None:
                    pre_rect = fitz.Rect(0, 0, pw, first_y_top)
                    pre_text = _clean_zone_text(page, pre_rect)
                    if pre_text:
                        active_section["text_parts"].append(pre_text)
                    for rows in extract_tables_from_rect(page, pre_rect):
                        active_section["tables"].append({"page": page_num, "page_ref": ref, "rows": rows})
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
                    zone_text = _clean_zone_text(page, zone_rect)
                    # INFOID sits on the same line as the heading (right margin) —
                    # it is above zone_rect, so search the heading row itself.
                    heading_rect   = fitz.Rect(0, y_top, pw, y_bottom)
                    oem_content_id = _extract_oem_content_id(page, heading_rect)
                    zone_tables = [
                        {"page": page_num, "page_ref": ref, "rows": rows}
                        for rows in extract_tables_from_rect(page, zone_rect)
                    ]

                    # Open new section
                    active_section = {
                        "heading":        display_name,
                        "role":           role,
                        "oem_content_id": oem_content_id,
                        "text_parts":     [zone_text] if zone_text else [],
                        "tables":         zone_tables,
                        "page_start":     page_num,
                        "page_end":       page_num,
                    }

        # Close the last open section after the page loop ends
        if active_section is not None:
            all_sections.append(_finalize_section(active_section))

    return {
        "raw_text":               "\n\n".join(raw_text_parts).strip(),
        "sections":               all_sections,
        "has_images":             has_images,
        "image_list":             image_list,
        "page_refs":              all_page_refs,
        "start_page_ref_footer":  start_page_ref_footer,
        "end_page_ref":           end_page_ref,
        "end_pdf_page":             last_processed,
        "section_code":             start_section_code,
        "stopped_at_type_boundary": stopped_at_type_boundary,
    }
