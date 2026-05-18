import contextlib
import io
import re
import sys
import fitz
from pathlib import Path
from patterns import CODE_RE
from patterns import REF_RE
from patterns import DTC_INDEX_HEADINGS
from patterns import DTC_INDEX_HEADINGS_STRICT
from content_extractor import read_page_ref


@contextlib.contextmanager
def _quiet():
    """Suppress stdout during find_tables() to hide PyMuPDF's 'Consider pymupdf_layout' advisory."""
    old = sys.stdout
    sys.stdout = io.StringIO()
    try:
        yield
    finally:
        sys.stdout = old


def _build_page_ref_map(pdf) -> dict:
    """
    Scan every page footer and build a page_ref ->pdf_page map.
    e.g. {"EVB-181": 288, "BRC-62": 95}  (pdf_page is 1-based)

    Used as a fallback when internal hyperlinks are absent or incomplete.
    A footer page ref is always accurate — it is printed on the page itself,
    whereas a hyperlink target can be wrong if the PDF was assembled incorrectly.
    """
    ref_map = {}
    for i in range(len(pdf)):
        ref = read_page_ref(pdf[i])
        if ref:
            ref_map[ref] = i + 1   # 1-based to match the convention used elsewhere
    return ref_map


def find_dtc_heading_y(page) -> float:
    """
    Look for a DTC index heading on a page.
    Returns the bottom y-coordinate of the heading block, or None if not found.

    Matches any heading in DTC_INDEX_HEADINGS (multi-manufacturer).
    INFOID: is used as an optional secondary signal for Nissan manuals but is
    NOT required — other OEMs don't use it.

    Fallback: some PDFs render the DTC Index heading as part of a preceding
    content block rather than as a standalone block (e.g. Nissan AV section).
    In that case no heading block matches, but the DTC index table is still
    present — detected by its header row containing 'DTC' and 'Display item'
    or 'Refer to'. Returns the top y-coordinate of that table header block.
    """
    blocks = page.get_text("blocks")

    for block in blocks:
        block_text = block[4].strip()
        first_line = block_text.split("\n")[0].strip().lower()

        if first_line in DTC_INDEX_HEADINGS:
            return block[3]

    # Fallback: look for a table header block that identifies a DTC index
    for block in blocks:
        block_text = block[4].strip().lower()
        if "dtc" in block_text and ("display item" in block_text or "refer to" in block_text):
            return block[1]  # top y of the block

    return None


def find_index_table(page, heading_y: float):
    """
    Find the DTC index table that starts below the DTC Index heading.

    Prefers the table whose header row contains a 'Reference' column — this
    distinguishes the real DTC index from a Pattern A/B/C/D table that may
    carry over from the previous page and appear above the index at the same Y.
    Falls back to the first table below heading_y if none has a Reference column.
    """
    with _quiet():
        tables = page.find_tables()

    candidates = [t for t in tables.tables if t.bbox[1] >= heading_y]
    if not candidates:
        return None

    # Prefer the table whose header contains 'Reference'
    for table in candidates:
        rows = table.extract()
        if rows and any("reference" in str(cell).lower() for cell in (rows[0] or [])):
            return table

    # ── Rejection check ───────────────────────────────────────────────────────
    # No 'Reference' column found in any candidate table.
    # Before falling back, check whether the first table's header contains words
    # that only appear in description/action tables — never in a real DTC index.
    # This prevents self-diagnosis result pages (e.g. AV-159) from being mistaken
    # for a DTC index when they share a heading like "Self-diagnosis results".
    first = candidates[0]
    rows  = first.extract()
    if rows and rows[0]:
        header_text     = " ".join(str(c).lower() for c in rows[0] if c)
        rejection_words = {"description", "action", "malfunction", "factor"}
        if any(word in header_text for word in rejection_words):
            return None   # not a DTC index table — reject

    return candidates[0]  # header may be garbled/missing but not disqualified


def detect_format(header_row: list) -> str:
    """
    Detect which table format this index uses.
    Format A: has a dedicated 'DTC' column
    Format B: no DTC column — codes are embedded in brackets like [U1000]
    """
    for cell in header_row:
        if cell and "dtc" in str(cell).lower():
            return "A"

    return "B"


def _ref_col_idx(header_row: list) -> int:
    """Return the column index of the Reference column. Falls back to last column."""
    for i, cell in enumerate(header_row):
        if cell and "reference" in str(cell).lower():
            return i
    return len(header_row) - 1


def _read_format_a_table(page, table, links: list, page_ref_map: dict) -> dict:
    """
    Extract DTC code ->{page, page_ref, title} directly from a Format A index table.

    Reads table rows instead of scanning the word layer.
    Handles merged reference cells via carry-forward: when the reference cell is
    empty the code belongs to the same group as the previous non-empty reference.

    Link matching: links are filtered to the reference column x zone and sorted by Y.
    Each non-empty reference cell starts a new group and consumes the next link in
    order. After consuming a link, any following links that share the same named
    destination (or page if no named destination) are skipped — they belong to
    sub-rows within the same group (e.g. MISSING MESSAGE / ERRATIC rows that each
    have their own hyperlink but all point to the same target).

    Fallback: when no hyperlink is available for a reference group, the reference
    text (e.g. "BRC-62") is looked up in page_ref_map (built from page footers).
    This makes the index resilient to PDFs with absent or broken internal links.

    Format A tables have columns: DTC | Display Item | Reference
    """
    rows = table.extract()
    if not rows or len(rows) < 2:
        return {}

    header  = rows[0] or []
    ref_col = _ref_col_idx(header)

    # ── Filter links to the reference column x zone ───────────────────────────
    # Reference column occupies the rightmost portion of the table.
    # Threshold at 60% across the table width is safely inside the ref column
    # for every Nissan-style index we have seen (actual boundary ≈ 66%).
    t_x0 = table.bbox[0]
    t_x1 = table.bbox[2]
    ref_x_threshold = t_x0 + (t_x1 - t_x0) * 0.60

    ref_links = sorted(
        [l for l in links if fitz.Rect(l["from"]).x0 >= ref_x_threshold],
        key=lambda l: fitz.Rect(l["from"]).y0,
    )

    results   = {}
    last_page = None
    last_ref  = None
    link_idx  = 0

    for row in rows[1:]:   # skip header
        if not row:
            continue

        # ── Code ─────────────────────────────────────────────────────────────
        raw   = str(row[0]).strip() if row[0] is not None else ""
        clean = re.sub(r"[^A-Z0-9]", "", raw.upper())
        if not CODE_RE.match(clean):
            continue
        code = clean

        # ── Title ─────────────────────────────────────────────────────────────
        title = str(row[1]).strip() if len(row) > 1 and row[1] is not None else ""
        title = re.sub(r"\[[PBCU][0-9A-F]{4}\]", "", title).strip()

        # ── Reference cell ────────────────────────────────────────────────────
        ref_raw = ""
        if ref_col >= 0 and len(row) > ref_col and row[ref_col] is not None:
            ref_raw = str(row[ref_col]).strip()

        if ref_raw:
            # New reference group — advance to the next link in the ref column
            m = REF_RE.search(ref_raw)
            last_ref = m.group(0) if m else None

            if link_idx < len(ref_links):
                link_ref = ref_links[link_idx].get("ref_text")

                # ── Cross-check ref text ──────────────────────────────────────
                # Verify the next link actually points to the expected reference.
                # When two adjacent codes share the same ref (e.g. B2900 and B2902
                # both mapping to VC-76), the sub-row skip for B2900 can advance
                # link_idx past all VC-76 links, leaving B2902 to consume B2980's
                # VC-77 link instead — a silent wrong-page assignment.
                # If refs don't match, leave the link unconsumed for the group
                # that genuinely owns it, and resolve this group via footer scan.
                if last_ref and link_ref and last_ref.upper() != link_ref.upper():
                    resolved = page_ref_map.get(last_ref) if page_ref_map else None
                    if resolved:
                        print(f"  [INFO index-match] link mismatch for [{code}]"
                              f" — expected '{last_ref}', got '{link_ref}'"
                              f" ->resolved to page {resolved} via footer scan")
                        last_page = resolved
                    else:
                        print(f"  [WARN index-match] link mismatch for [{code}]"
                              f" — expected '{last_ref}', got '{link_ref}', footer scan also failed")
                        last_page = None
                else:
                    # Refs match (or no ref text to verify) — trust the hyperlink
                    last_page = ref_links[link_idx]["page"] + 1  # 0-based ->1-based
                    link_idx  += 1

                    # ── Skip sub-row links ────────────────────────────────────
                    # Some index tables have multiple rows per code group (e.g.
                    # MISSING MESSAGE, ERRATIC). Each sub-row has its own hyperlink
                    # all pointing to the same destination. Skip them so the next
                    # group consumes the correct link.
                    # Use nameddest as the identity key — more precise than page.
                    consumed_dest = (ref_links[link_idx - 1].get("nameddest")
                                     or ref_links[link_idx - 1]["page"])
                    while link_idx < len(ref_links):
                        next_dest = (ref_links[link_idx].get("nameddest")
                                     or ref_links[link_idx]["page"])
                        if next_dest != consumed_dest:
                            break      # different destination = next group starts here
                        link_idx += 1  # same destination = sub-row link, skip it

            elif last_ref and page_ref_map:
                # No hyperlink — resolve via footer scan fallback
                last_page = page_ref_map.get(last_ref)
                if last_page:
                    print(f"  [INFO index-match] no link for [{code}]"
                          f" — resolved '{last_ref}' ->page {last_page} via footer scan")
                else:
                    print(f"  [WARN index-match] no link and no footer match for [{code}]"
                          f" — ref '{last_ref}' not found in any page footer")
                    last_page = None
            else:
                print(f"  [WARN index-match] no link for ref group [{code}]"
                      f" — ref text '{ref_raw}' has no hyperlink")
                last_page = None

        # Codes with empty reference inherit the current group's page (carry-forward)
        if last_page is not None:
            results[code] = {
                "page":     last_page,
                "title":    title,
                "page_ref": last_ref,
            }

    return results


# ── Format B fallback: Y-based link matching ─────────────────────────────────
# Used for index tables with no DTC/Reference columns (codes embedded in brackets).
# Also used for multi-page index continuation pages.

_ROW_Y_TOL  = 4    # pt — codes within this Y band share one visual row
_LINK_Y_TOL = 20   # pt — link midY must be within this of a code row's Y
_BLOCK_GAP  = 40   # pt — Y gap larger than this starts a new block


def extract_codes_with_y(page, fmt: str, min_y: float = 0.0) -> list:
    """
    Extract DTC codes, their y-positions, and titles from a page.
    Title = all words on the same y-level as the code, to the right of it.
    Returns a list of (code, y, title) tuples.

    min_y: skip any word whose top edge is above this Y value.
           Use table.bbox[1] on the first index page to exclude codes that
           belong to a carry-over Pattern A/B/C/D table above the DTC index.
    """
    words = page.get_text("words")  # each word: (x0, y0, x1, y1, text, ...)
    results = []

    for i, word in enumerate(words):
        word_text = word[4]
        y_pos = word[1]   # y0 = top edge of this word

        if y_pos < min_y:
            continue

        if fmt == "A":
            clean = re.sub(r"[^A-Z0-9]", "", word_text.upper())
            if CODE_RE.match(clean):
                title_words = []
                ref_text   = None    # reference text on this row, e.g. "SEC-52" or "EVC-161"
                title_done = False   # set True once we hit a dash/digit separator column
                for w in words:
                    if abs(w[1] - y_pos) >= 3:
                        continue
                    if w[0] <= word[2]:
                        continue
                    cell = w[4].strip()
                    # Always check for ref text first — it lives in the rightmost column.
                    # REF_RE requires letters-dash-digits (e.g. SEC-52, EVC-161) so it
                    # won't accidentally match normal title words.
                    m_ref = REF_RE.match(cell)
                    if m_ref:
                        ref_text = m_ref.group(0)
                        break   # ref text is the last thing we need on this row
                    # Stop collecting title words once we hit a separator column
                    # (dash cell, a plain number, or another DTC code), but keep
                    # scanning so we can still find the ref text further right.
                    if not title_done:
                        if re.match(r"^[×—x]$", cell, re.IGNORECASE):
                            title_done = True
                        elif re.match(r"^\d+$", cell):
                            title_done = True
                        elif CODE_RE.match(re.sub(r"[^A-Z0-9]", "", cell.upper())):
                            title_done = True
                        else:
                            title_words.append(cell)

                title = " ".join(title_words).strip()
                title = re.sub(r"\[[PBCU][0-9A-F]{4}\]", "", title, flags=re.IGNORECASE).strip()
                results.append((clean, y_pos, title, ref_text))   # 4-tuple

        else:
            m = re.match(r"\[([PBCU][0-9A-F]{4})\]", word_text, re.IGNORECASE)
            if m:
                results.append((m.group(1).upper(), y_pos, "", None))   # 4-tuple, no ref

    return results


def match_codes_to_links(codes_with_y: list, links: list, page_ref_map: dict | None = None) -> dict:
    """
    Match each DTC code row to its page-ref hyperlink using row/block-aware matching.
    Used for Format B indexes and continuation pages.

    page_ref_map is accepted for API consistency but is not used here — Format B
    and continuation pages embed no reference text in their rows, so there is
    nothing to look up in the map without links.

    Returns: { code: {"page": int, "title": str, "page_ref": str|None}, ... }
    """
    if not codes_with_y:
        return {}
    if not links:
        codes_str = ", ".join(c[0] for c in codes_with_y[:5])
        more = f" (+{len(codes_with_y) - 5} more)" if len(codes_with_y) > 5 else ""
        print(f"  [WARN index-match] no links on this page — cannot resolve"
              f" {len(codes_with_y)} codes ({codes_str}{more})")
        return {}

    def link_midy(lnk: dict) -> float:
        r = lnk["from"]
        return (r.y0 + r.y1) / 2

    rows: list[dict] = []
    for code, y, title, ref_text in sorted(codes_with_y, key=lambda x: x[1]):
        if rows and abs(y - rows[-1]["y"]) <= _ROW_Y_TOL:
            rows[-1]["items"].append((code, y, title, ref_text))
        else:
            rows.append({"y": y, "items": [(code, y, title, ref_text)]})

    blocks: list[list[dict]] = [[rows[0]]]
    for row in rows[1:]:
        if row["y"] - blocks[-1][-1]["y"] > _BLOCK_GAP:
            blocks.append([])
        blocks[-1].append(row)

    results: dict = {}

    for block in blocks:
        b_top       = block[0]["y"] - _LINK_Y_TOL
        b_bottom    = block[-1]["y"] + _LINK_Y_TOL
        block_links = [lnk for lnk in links
                       if b_top <= link_midy(lnk) <= b_bottom]

        for row in block:
            ry        = row["y"]
            codes_str = ", ".join(c[0] for c in row["items"])
            row_ref   = row["items"][0][3] if row["items"] else None   # expected ref text
            nearby    = [lnk for lnk in block_links
                         if abs(link_midy(lnk) - ry) <= _LINK_Y_TOL]

            if not nearby:
                # No link found — try footer scan using the ref text from the word layer
                # (e.g. "SEC-52" — a cross-section ref with no hyperlink in this PDF)
                if row_ref and page_ref_map:
                    resolved = page_ref_map.get(row_ref)
                    if resolved:
                        print(f"  [INFO index-match] no link for [{codes_str}]"
                              f" — resolved '{row_ref}' ->page {resolved} via footer scan")
                        for code, _y, item_title, _ in row["items"]:
                            results[code] = {
                                "page":     resolved,
                                "title":    item_title,
                                "page_ref": row_ref,
                            }
                        continue
                print(f"  [WARN index-match] no link for [{codes_str}] at Y={ry:.1f} "
                      f"(block Y {block[0]['y']:.0f}-{block[-1]['y']:.0f}, "
                      f"{len(block_links)} block links)")
                continue

            best     = min(nearby, key=lambda lnk: abs(link_midy(lnk) - ry))
            link_ref = best.get("ref_text")

            # Cross-check: when we know the expected ref text, verify the matched
            # link actually points to the right destination. A row with a cross-section
            # ref (e.g. SEC-51) has no hyperlink — it can get matched to a nearby EVC
            # link purely by Y proximity, which gives the wrong page.
            if row_ref and link_ref and row_ref.upper() != link_ref.upper():
                resolved = page_ref_map.get(row_ref) if page_ref_map else None
                if resolved:
                    print(f"  [INFO index-match] link mismatch for [{codes_str}]"
                          f" — expected '{row_ref}', got '{link_ref}'"
                          f" ->resolved to page {resolved} via footer scan")
                    for code, _y, item_title, _ in row["items"]:
                        results[code] = {
                            "page":     resolved,
                            "title":    item_title,
                            "page_ref": row_ref,
                        }
                    continue
                # Footer scan also failed — fall through and use the link with a warning
                print(f"  [WARN index-match] link mismatch for [{codes_str}]"
                      f" — expected '{row_ref}', got '{link_ref}', footer scan also failed")

            target_page = best["page"] + 1

            for code, _y, title, _ in row["items"]:
                results[code] = {
                    "page":     target_page,
                    "title":    title,
                    "page_ref": link_ref,
                }

    return results


def _find_via_bookmarks(pdf) -> list[int]:
    """
    Try to locate DTC index pages using the PDF outline (bookmarks).

    pdf.get_toc() returns a list of entries — each entry is a list with at least
    3 elements: [level, title, page, ...]. Extra elements may exist depending on
    the PyMuPDF version and the simple= parameter, so we index by position rather
    than unpacking with a fixed-length tuple to avoid ValueError.

    page is 1-based in PyMuPDF's get_toc().

    Returns a list of 1-based PDF page numbers whose bookmark title matches a known
    DTC index heading, or [] if the PDF has no bookmarks or no matching entry.
    """
    toc = pdf.get_toc()   # full outline tree — one call, fast
    if not toc:
        return []          # PDF has no bookmarks at all

    found = []
    for entry in toc:
        title = entry[1]   # index by position — safe regardless of entry length
        page  = entry[2]   # 1-based PDF page number
        if any(h in title.lower() for h in DTC_INDEX_HEADINGS_STRICT):
            found.append(page)

    return found


def build_index(pdf_path: Path) -> dict:
    """
    Scan all pages for DTC index tables.
    Returns: { "U1000": {"pages": [181], "page_refs": ["EVB-181"], "title": "..."}, ... }
    One code can map to multiple pages.

    Format A index pages (DTC | Display Item | Reference columns) use table-based
    extraction: rows are read directly, merged reference cells are handled via
    carry-forward, and links are matched to reference groups in Y order.

    Format B pages and multi-page continuation pages fall back to Y-based matching.
    """
    with fitz.open(str(pdf_path)) as pdf:
        results   = {}
        seen_pages = set()

        print(f"Step 1 — scanning {len(pdf)} pages for DTC index...")

        # ── Footer scan map ───────────────────────────────────────────────────
        # Built once — used as fallback when hyperlinks are absent or incomplete.
        # Scanning all footers adds ~0.1s on a 1500-page PDF (text clip only).
        page_ref_map = _build_page_ref_map(pdf)
        if not page_ref_map:
            print("  [WARN] no page refs found in footers — footer scan fallback unavailable")

        # Check overall link availability for an early warning (short-circuits on first hit)
        has_any_links = False
        for _page in pdf:
            if any(l["kind"] == 4 for l in _page.get_links()):
                has_any_links = True
                break
        if not has_any_links:
            print("  [WARN] PDF has no internal hyperlinks — index will rely entirely on footer scan")

        # ── Bookmark-based index discovery (fast path) ────────────────────────
        # Try the PDF outline first — if the manual has bookmarks with DTC index
        # entries, we jump directly to those pages instead of scanning all pages.
        # Falls back to full heading scan if bookmarks are absent or yield nothing.
        bookmark_pages = _find_via_bookmarks(pdf)
        if bookmark_pages:
            print(f"  [INFO] bookmarks found — DTC index pages: {bookmark_pages}")
            bookmark_set = set(bookmark_pages)   # 1-based, for O(1) lookup
        else:
            print(f"  [INFO] no bookmarks — falling back to full heading scan")
            bookmark_set = None                  # None = scan all pages

        page_num = 0
        while page_num < len(pdf):
            # If bookmarks found, skip any page not listed in the bookmark set.
            # Convert page_num (0-based) to 1-based for the comparison.
            if bookmark_set is not None and (page_num + 1) not in bookmark_set:
                page_num += 1
                continue
            page = pdf[page_num]

            page_text_lower = page.get_text("text").lower()
            if not any(h in page_text_lower for h in DTC_INDEX_HEADINGS):
                page_num += 1
                continue

            heading_y = find_dtc_heading_y(page)
            if heading_y is None:
                page_num += 1
                continue

            table = find_index_table(page, heading_y)
            table_page_num = page_num

            if table is None:
                # Before checking the next page, test whether the current page
                # already has DTC codes via Y-based scan (borderless table layout).
                # If it does, stay on this page — don't grab the next page's table.
                _probe = extract_codes_with_y(page, fmt="A", min_y=heading_y)
                if not _probe and page_num + 1 < len(pdf):
                    next_page = pdf[page_num + 1]
                    with _quiet():
                        tables = next_page.find_tables()
                    if tables.tables:
                        table = tables.tables[0]
                        table_page_num = page_num + 1

            if table_page_num in seen_pages:
                page_num += 1
                continue

            print(f"  Found index on page {table_page_num + 1}")

            if table is not None:
                rows = table.extract()
                if not rows:
                    page_num += 1
                    continue
                fmt           = detect_format(rows[0])
                index_table_y = table.bbox[1]
            else:
                # Borderless table — use Y-based text extraction.
                # Assume Format A since DTC/Display item/Refer to columns are present.
                fmt           = "A"
                index_table_y = heading_y

            current_num = table_page_num
            while current_num < len(pdf):
                if current_num in seen_pages:
                    break

                current_page = pdf[current_num]

                if current_num > table_page_num:
                    if find_dtc_heading_y(current_page) is not None:
                        break
                    codes_check = extract_codes_with_y(current_page, fmt)
                    if not codes_check:
                        break

                # Collect all kind=4 links with their visible ref text
                links = []
                for l in current_page.get_links():
                    if l["kind"] != 4:
                        continue
                    raw = current_page.get_text("text", clip=l["from"]).strip()
                    m   = REF_RE.search(raw)
                    l["ref_text"] = m.group(0) if m else None
                    links.append(l)

                if fmt == "A" and current_num == table_page_num and table is not None:
                    # ── Table-based extraction for Format A index page ────────
                    # Reads rows directly — handles merged reference cells,
                    # no Y-proximity matching needed.
                    page_results = _read_format_a_table(current_page, table, links, page_ref_map)
                else:
                    # ── Y-based fallback for Format B and continuation pages ──
                    min_y        = index_table_y if current_num == table_page_num else 0.0
                    codes_with_y = extract_codes_with_y(current_page, fmt, min_y=min_y)
                    page_results = match_codes_to_links(codes_with_y, links, page_ref_map)

                for code, info in page_results.items():
                    if code not in results:
                        results[code] = {"pages": [], "page_refs": [], "title": info["title"]}
                    # Skip duplicate — same code pointing to the same page from
                    # two different index sections (e.g. U1000 in both AV index pages)
                    if info["page"] not in results[code]["pages"]:
                        results[code]["pages"].append(info["page"])
                        results[code]["page_refs"].append(info["page_ref"])

                seen_pages.add(current_num)
                current_num += 1

            page_num += 1

        print(f"  Found {len(results)} codes")
        return results
