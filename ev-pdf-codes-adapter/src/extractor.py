"""
extractor.py
============
Extraction logic for one manual PDF.
Called by pipeline.py.
"""

import re
import hashlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from shared.document_id import compute_document_id
from pdf_profile import profile_pdf
from index_builder import build_index
from content_extractor import extract_content, _dedup_merged_cells
from vehicle_info import extract_vehicle_info
from type_detector import detect_manual_types


def _common_title_prefix(titles: list[str]) -> str:
    """
    Return the longest common word-level prefix shared by all titles.
    E.g. ["CELL OVER DISCHARGE MODULE25", "CELL OVER DISCHARGE MODULE26"]
         -> "CELL OVER DISCHARGE"
    """
    if not titles:
        return ""
    split = [t.split() for t in titles]
    min_len = min(len(s) for s in split)
    common = []
    for i in range(min_len):
        word = split[0][i]
        if all(s[i] == word for s in split):
            common.append(word)
        else:
            break
    return " ".join(common)


def _normalize_title(codes: list, code_titles: dict) -> str | None:
    """
    Build a compact title for a DTC record.
    Single code  -> "P0A0D HV SYSTEM INTERLOCK ERROR"
    Multiple codes -> "P3031-P303C CELL CONT"  (code range + common title prefix)
    Sidebar letters (e.g. 'E CELL CONT ASIC4') are stripped before comparison.
    """
    raw_titles = [code_titles.get(c, "") for c in codes if code_titles.get(c)]
    if not raw_titles:
        return None
    # Strip inline sidebar prefix: a single uppercase letter at the start
    # e.g. "E CELL CONT ASIC4" -> "CELL CONT ASIC4"
    # Only strips a single leading letter — won't touch "DLC DIAGNOSIS VCM"
    _leading = re.compile(r'^[A-Z] ')
    titles = [_leading.sub("", t).strip() for t in raw_titles]
    titles = [t for t in titles if t]
    if not titles:
        return None

    if len(codes) == 1:
        return f"{codes[0]} {titles[0]}".strip()

    sorted_codes = sorted(codes)
    first_code   = sorted_codes[0]
    last_code    = sorted_codes[-1]
    common       = _common_title_prefix(titles)
    if common:
        return f"{first_code}-{last_code} {common}"
    return f"{first_code}-{last_code}"


def _headers_match(row_a: list, row_b: list) -> bool:
    """
    Return True when two header rows represent the same column layout.
    Ignores trailing empty cells so tables with different padding still merge.
    Used by _merge_continued_tables to detect Nissan's reprinted page headers.
    """
    def strip_trailing(row):
        r = list(row)
        while r and r[-1] == '':
            r.pop()
        return r
    return strip_trailing(row_a) == strip_trailing(row_b)


def _merge_continued_tables(tables: list, notes: list, record_num: int) -> tuple[list, set]:
    """
    Detect cross-page table continuations and produce table_groups.

    Two consecutive tables are considered a continuation when they share
    the same section_id and matching header rows (_headers_match).
    The duplicate header row is dropped from the second table onward.

    Changed role: no longer replaces raw tables.
    Returns (table_groups, absorbed_ids) where:
      - table_groups: one group dict per set of 2+ merged tables
      - absorbed_ids: set of table_ids consumed into a group

    Raw tables in `tables` are NOT modified.
    Single-page tables that form no continuation produce no group.
    """
    if not tables:
        return [], set()

    groups   = []
    absorbed = set()
    g_count  = 1
    skip     = set()

    for i, tbl in enumerate(tables):
        if i in skip:
            continue

        source_ids  = [tbl["table_id"]]
        merged_rows = list(tbl["rows"])
        pages       = [tbl["page"]]
        page_refs   = [tbl["page_ref"]] if tbl.get("page_ref") else []

        for j in range(i + 1, len(tables)):
            if j in skip:
                continue
            nxt = tables[j]
            if (nxt["section_id"] == tbl["section_id"]
                    and nxt["rows"] and tbl["rows"]
                    and nxt["page"] != pages[-1]          # different page — true cross-page continuation
                    and _headers_match(nxt["rows"][0], tbl["rows"][0])):
                source_ids.append(nxt["table_id"])
                merged_rows.extend(nxt["rows"][1:])
                pages.append(nxt["page"])
                if nxt.get("page_ref"):
                    page_refs.append(nxt["page_ref"])
                skip.add(j)
            else:
                break   # only merge consecutive tables in the same section

        if len(source_ids) > 1:
            group_id = f"r{record_num}_g{g_count}"
            for tid in source_ids:
                absorbed.add(tid)
            groups.append({
                "group_id":         group_id,
                "source_table_ids": source_ids,
                "section_id":       tbl["section_id"],
                "role":             tbl["role"],
                "start_pdf_page":   pages[0],
                "end_pdf_page":     pages[-1],
                "page_refs":        page_refs,
                "raw_rows":         merged_rows,
            })
            g_count += 1
            notes.append(
                f"{group_id} merged {len(source_ids)} tables across pages: {', '.join(page_refs)}"
            )

    return groups, absorbed


# DTC code and step number patterns — used by structural header detection below.
# DTC-specific patterns are acceptable in this adapter (targets DTC content).
_DTC_CODE_RE = re.compile(r'^[A-Z][0-9A-Z]{4}$')      # e.g. P303D, P338A, P0A0D
_STEP_NUM_RE = re.compile(r'^\d+$')                    # plain integer: 1, 2, 42

_ALPHA_RE = re.compile(r'^[A-Za-z\s]+$')   # purely alphabetic label (no digits)


def _is_subheader_row(row: list, known_codes: set | None = None) -> bool:
    """
    Return True if every non-empty cell in this row could be a header label.
    A sub-header contains no DTC codes and no plain integers — those only
    appear in data rows.

    known_codes — exact set of codes from the DTC index (preferred over regex).
    """
    for cell in row:
        v = str(cell).strip()
        if not v:
            continue
        if known_codes and v in known_codes:
            return False
        if _DTC_CODE_RE.match(v):
            return False
        if _STEP_NUM_RE.match(v):
            return False
    return True


def _row_has_dtc_codes(row: list, known_codes: set | None = None) -> bool:
    """Return True if any cell in this row is a known DTC code.

    DTC codes are data values — a row containing them must never be
    used as a column header row.

    known_codes (preferred) — exact set from the DTC index.
    Falls back to _DTC_CODE_RE when not supplied.
    """
    for c in row:
        v = str(c).strip()
        if not v:
            continue
        if known_codes and v in known_codes:
            return True
        if _DTC_CODE_RE.match(v):
            return True
    return False


def _detect_header_rows(raw_rows: list, known_codes: set | None = None) -> int:
    """
    Return how many leading rows form the header (1 or 2).

    known_codes — exact set of codes from the DTC index.  Passed to
    _is_subheader_row so that any row containing a known code is immediately
    recognised as data, not a header.

    A second header row is detected when:
    - row 1 passes _is_subheader_row (no DTC codes, no plain integers), AND one
      of the following structural signals is present:

      Gap-fill: at least one cell in row 1 occupies a position that was empty
      in row 0 — row 1 extends the header (e.g. "Module" spans two columns,
      row 1 provides "Connector" and "Terminal No." under it).

      Parent-category: all non-empty cells in row 0 are purely alphabetic
      category labels ("Module", "Controller") and row 1 has at least one
      overlapping non-empty cell (a child label under the same column).
    """
    if len(raw_rows) < 3:
        return 1

    row0 = raw_rows[0]
    row1 = raw_rows[1]

    if not _is_subheader_row(row1, known_codes):
        return 1

    n = max(len(row0), len(row1))

    # Signal 1 — gap-fill: row 1 has a value where row 0 is empty
    for i in range(n):
        a = str(row0[i]).strip() if i < len(row0) else ''
        b = str(row1[i]).strip() if i < len(row1) else ''
        if not a and b:
            return 2

    # Signal 2 — parent-category: row 0 is all pure-alphabetic labels AND
    # row 1 overlaps with at least one of those positions
    row0_all_label = all(
        not str(c).strip() or bool(_ALPHA_RE.match(str(c).strip()))
        for c in row0
    )
    has_overlap = any(
        (str(row0[i]).strip() if i < len(row0) else '')
        and (str(row1[i]).strip() if i < len(row1) else '')
        for i in range(n)
    )
    if row0_all_label and has_overlap:
        return 2

    return 1


def _merge_header_rows(row0: list, row1: list) -> list:
    """
    Combine two header rows into single column labels.

      "Module"  + "Connector"    → "Module Connector"
      ""        + "Terminal No." → "Terminal No."
      "Existed" + ""             → "Existed"
      ""        + ""             → ""
    """
    n = max(len(row0), len(row1))
    result = []
    for i in range(n):
        a = str(row0[i]).strip() if i < len(row0) else ''
        b = str(row1[i]).strip() if i < len(row1) else ''
        if a and b:
            result.append(f"{a} {b}")
        else:
            result.append(a or b)
    return result


def _render_raw_table_text(raw_rows: list) -> str:
    """
    Render raw_rows as a pipe-delimited string — direct mechanical output.
    Each row becomes one line; cells are joined with ' | '.
    None → empty string. No cleanup, no inference. What was extracted, as-is.
    """
    lines = []
    for row in raw_rows:
        cells = [str(c) if c is not None else "" for c in row]
        lines.append(" | ".join(cells))
    return "\n".join(lines)


def _clean_table_cell(cell: str) -> str:
    """
    Apply the allowed minimal cleanup to a single table cell.
    Allowed: join soft hyphen line breaks, normalize whitespace within lines.
    Not allowed: rewrite meaning, move words, infer structure.
    """
    # Join soft hyphen line breaks: "commu-\nnication" → "communication"
    cell = re.sub(r"(\w+)-\n([a-z])", r"\1\2", cell)
    # Normalize whitespace within each line (collapse multiple spaces)
    lines = [" ".join(ln.split()) for ln in cell.split("\n")]
    return "\n".join(lines).strip()


def _render_cleaned_table_text(raw_rows: list) -> str:
    """
    Render raw_rows as a pipe-delimited string with minimal readability cleanup.
    Applies _clean_table_cell to each cell: soft hyphen joins + whitespace normalisation.
    Structure (row/column order, pipe layout) is identical to raw_table_text.
    """
    lines = []
    for row in raw_rows:
        cells = [_clean_table_cell(str(c) if c is not None else "") for c in row]
        lines.append(" | ".join(cells))
    return "\n".join(lines)


def _fill_carry_forward(raw_rows: list, header_count: int) -> list:
    """
    Fill empty cells by propagating the value from the row above.
    Applied only to data rows — rows after the header rows are left unchanged.

    PDF tables use empty cells as shorthand for "same as above".
    Filling them here makes every data row self-contained so the importer
    does not need to re-implement carry-forward logic.
    """
    if not raw_rows or header_count >= len(raw_rows):
        return raw_rows
    result = [list(row) for row in raw_rows]
    for row_idx in range(header_count + 1, len(result)):
        prev = result[row_idx - 1]
        curr = result[row_idx]
        for col_idx in range(min(len(prev), len(curr))):
            if curr[col_idx] == "" and prev[col_idx] != "":
                curr[col_idx] = prev[col_idx]
    return result


def _make_record_id(document_id: str, manual_type: str | None, start_pdf_page: int) -> str:
    """
    Generate a unique, deterministic ID for a DTC record.
    SHA256 of (document_id + manual_type_str + start_pdf_page).
    manual_type_str is "" when manual_type is None — formula is identical to
    the pre-#28 formula for PDFs with no TYPE boundaries, so existing IDs
    are unchanged.
    Truncated to 16 hex chars for readability.
    """
    manual_type_str = manual_type if manual_type is not None else ""
    raw = f"{document_id}{manual_type_str}{start_pdf_page}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def extract_records(pdf_path: Path, output_dir: Path) -> dict:
    """
    Main function called by pipeline.py.
    Returns one document-level JSON object for this PDF.
    output_dir is where image files will be saved.
    """
    source = pdf_path.name

    # SHA256 of the raw PDF bytes — same file different name = same ID
    document_id = compute_document_id(pdf_path)

    # ── Profile the PDF ───────────────────────────────────────────────────────
    metadata, pdf_profile = profile_pdf(pdf_path)

    # ── Extract vehicle info ──────────────────────────────────────────────────
    vehicle = extract_vehicle_info(pdf_path, metadata)
    # Strip internal field not in the shared envelope
    if isinstance(vehicle, dict) and isinstance(vehicle.get("source"), dict):
        vehicle["source"].pop("make_from_lookup", None)

    # ── Build DTC index ───────────────────────────────────────────────────────
    index = build_index(pdf_path)

    if not index:
        print("No codes found.")
        return {}

    # ── Detect manual-level TYPE boundaries (pre-pass) ────────────────────────
    # Returns {pdf_page (1-based): "TYPE N" | None}.
    # None on every page means no TYPE headings found — manual_type omitted.
    print("\nStep 2 — scanning for manual TYPE boundaries...")
    page_type_map = detect_manual_types(pdf_path)
    type_values = set(page_type_map.values()) - {None}
    if type_values:
        print(f"  Found TYPE boundaries: {sorted(type_values)}")
    else:
        print("  No TYPE boundaries found — single-type document")

    # Flatten index into page_to_codes and code_titles
    page_to_codes: dict[int, list] = {}
    code_titles:   dict[str, str]  = {}
    page_to_ref:   dict[int, str]  = {}

    for code, info in index.items():
        code_titles[code] = info["title"]
        for i, page_num in enumerate(info["pages"]):
            page_to_codes.setdefault(page_num, []).append(code)
            # first code to claim the page sets the printed ref
            if page_num not in page_to_ref and info["page_refs"][i]:
                page_to_ref[page_num] = info["page_refs"][i]

    print(f"\nExtracting content for {len(index)} codes across {len(page_to_codes)} pages...")

    records          = []
    seen_xrefs       = set()
    seen_hashes      = {}
    record_num       = 0   # incremented per TYPE segment, not per index entry
    doc_section_code = None  # first section code seen across all records

    for page_num, codes in sorted(page_to_codes.items()):
        print(f"  Page {page_num} -> {codes}")

        # ── TYPE-segment loop ─────────────────────────────────────────────────
        # A DTC block may span a TYPE boundary.  When extract_content signals
        # stopped_at_type_boundary, we create a record for the current segment
        # and restart extraction from the boundary page as a new record under
        # the new manual_type.  No pages are silently dropped.
        seg_start = page_num
        while seg_start is not None:
            record_num  += 1
            manual_type  = page_type_map.get(seg_start)

            page_ref_base = f"{pdf_path.stem}-{seg_start}"
            content = extract_content(
                pdf_path, seg_start, codes, output_dir,
                page_ref_base, seen_xrefs, seen_hashes,
                page_type_map=page_type_map,
            )

            # ── Cross-check: index ref vs footer ref ──────────────────────────
            # Only meaningful for the first segment (index only lists start page)
            index_ref  = page_to_ref.get(seg_start)
            footer_ref = content["start_page_ref_footer"]
            warnings   = []
            if index_ref and footer_ref and index_ref != footer_ref:
                msg = f"page_ref mismatch on PDF page {seg_start}: index={index_ref}, footer={footer_ref}"
                print(f"  [WARN] {msg}")
                warnings.append(msg)

            # Surface unknown headings found by structural detection
            for uh_warn in content.get("unknown_heading_warnings", []):
                print(f"  [WARN] {uh_warn}")
                warnings.append(uh_warn)

            # ── page_refs list ────────────────────────────────────────────────
            page_refs    = content["page_refs"]
            section_code = content.get("section_code")
            if section_code and doc_section_code is None:
                doc_section_code = section_code

            # ── DTC title ─────────────────────────────────────────────────────
            dtc_title = _normalize_title(codes, code_titles)

            # ── Sections — assign section_id to each ─────────────────────────
            sections = []
            for s_idx, sec in enumerate(content["sections"]):
                sections.append({
                    "section_id":     f"r{record_num}_s{s_idx + 1}",
                    "heading":        sec["heading"],
                    "role":           sec["role"],
                    "oem_content_id": sec.get("oem_content_id"),
                    "cleaned_text":   sec.get("cleaned_text"),
                    "raw_text":       sec.get("raw_text"),
                    "page_start":     sec["page_start"],
                    "page_end":       sec["page_end"],
                })

            # ── Tables — flat list, each linked to its section via section_id ─
            notes   = []
            tables  = []
            t_count = 1
            for s_idx, sec in enumerate(content["sections"]):
                section_id = f"r{record_num}_s{s_idx + 1}"
                for tbl in sec["tables"]:
                    tables.append({
                        "table_id":       f"r{record_num}_t{t_count}",
                        "section_id":     section_id,
                        "heading_nearby": sec["heading"],
                        "role":           sec["role"],
                        "page":           tbl["page"],
                        "page_ref":       tbl["page_ref"],
                        "rows":           tbl["rows"],
                        "extraction":     tbl["extraction"],
                    })
                    t_count += 1

            # Apply carry-forward fill and detect headers before merging so
            # table_groups also receive complete rows.
            known_codes_set = set(codes)
            for tbl in tables:
                raw          = tbl["rows"]
                header_count = _detect_header_rows(raw, known_codes_set)
                filled = _fill_carry_forward(raw, header_count)
                tbl["rows"]          = _dedup_merged_cells(filled)
                tbl["_header_count"] = header_count

            # Detect cross-page continuations → table_groups (raw tables unchanged)
            table_groups, absorbed_ids = _merge_continued_tables(tables, notes, record_num)

            # Finalize raw tables: rename location fields, rows → raw_rows.
            for tbl in tables:
                raw          = tbl.pop("rows")
                page         = tbl.pop("page")
                pr           = tbl.pop("page_ref")
                extraction   = tbl.pop("extraction")
                header_count = tbl.pop("_header_count")
                tbl["start_pdf_page"] = page
                tbl["end_pdf_page"]   = page
                tbl["page_refs"]      = [pr] if pr else []
                tbl["raw_rows"]            = raw
                tbl["raw_table_text"]      = _render_raw_table_text(raw)
                tbl["cleaned_table_text"]  = _render_cleaned_table_text(raw)
                # header_rows_hint — raw heuristic count, may undercount
                # multi-level headers (3+ rows).  Importer should verify.
                extraction["header_rows_hint"] = header_count
                # partial — True when the row immediately after the detected
                # headers also passes the sub-header test, indicating a 3+
                # level header structure that the heuristic cannot fully count.
                if (len(raw) > header_count
                        and _is_subheader_row(raw[header_count], known_codes_set)):
                    extraction["partial"] = True
                tbl["extraction"] = extraction

            # ── Images — enriched with metadata ──────────────────────────────
            # Assign each image to the last section whose page_start is on or
            # before the image's pdf_page.  Sections are ordered sequentially
            # so the last qualifying entry is the active section at that point.
            images = []
            for i_idx, img in enumerate(content["image_list"]):
                img_page = img["pdf_page"]
                section_id_for_img = None
                for sec in sections:
                    if sec["page_start"] <= img_page:
                        section_id_for_img = sec["section_id"]
                    else:
                        break
                images.append({
                    "image_id":   f"r{record_num}_i{i_idx + 1}",
                    "section_id": section_id_for_img,
                    "pdf_page":   img_page,
                    "page_ref":   img["page_ref"],
                    "image_path": img["filename"],
                    "caption":    img.get("caption"),
                    "role":       "unknown",
                })

            records.append({
                "record_id":   _make_record_id(document_id, manual_type, seg_start),
                "record_type": "dtc_block",

                "codes": codes,
                "title": dtc_title,

                **({"manual_type": manual_type} if manual_type is not None else {}),

                "location": {
                    "start_pdf_page": seg_start,
                    "end_pdf_page":   content["end_pdf_page"],
                    "page_refs":      page_refs,
                    **({"section_code": section_code} if section_code else {}),
                },

                "sections":     sections,
                "tables":       tables,
                "table_groups": table_groups,
                "images":       images,
                "notes":        notes,

                "extraction": {
                    "status":   "success",
                    "ocr_used": False,
                    "warnings": warnings,
                },
            })

            # ── Advance to next TYPE segment if boundary was hit ──────────────
            if content["stopped_at_type_boundary"]:
                seg_start = content["end_pdf_page"] + 1
            else:
                seg_start = None

    # Strip internal field not in the shared envelope
    profile_out = {k: v for k, v in pdf_profile.items() if k != "link_count_sample"}

    return {
        "schema_version":         "1.0",
        "schema_type":            "shared_document_profile",
        "adapter_schema_version": 5,
        "document_id":            document_id,
        "source_file":            source,
        "metadata":               metadata,
        "pdf_profile":            profile_out,
        "vehicle":                vehicle,
        "section": {
            "code":        doc_section_code,
            "name":        None,
            "manual_type": None,
        },
        "processing": {
            "adapter_name":         "ev-pdf-codes-adapter",
            "extraction_completed": True,
            "errors":               [],
        },
        "records": records,
    }
