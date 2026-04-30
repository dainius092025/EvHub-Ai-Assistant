"""
extractor.py
============
Extraction logic for one manual PDF.
Called by pipeline.py.
"""

import re
import hashlib
from pathlib import Path

from pdf_profile import profile_pdf
from index_builder import build_index
from content_extractor import extract_content
from vehicle_info import extract_vehicle_info


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


_DTC_CODE_RE = re.compile(r'^[A-Z][0-9A-Z]{4}$')      # e.g. P303D, P338A, P0A0D
_STEP_NUM_RE = re.compile(r'^\d+$')                    # plain integer: 1, 2, 42


def _slugify(text: str) -> str:
    """Convert a column header string to a snake_case dict key."""
    text = str(text).strip().lower()
    text = re.sub(r'[^a-z0-9]+', '_', text)
    return text.strip('_') or "col"


def _is_strong_identifier(value: str, known_codes: set | None = None) -> bool:
    """Return True if a cell value is a known DTC code or a plain step number.

    known_codes (preferred) — the exact set of codes from the DTC index for
    this record.  When provided, membership check replaces regex so the
    function works for any DTC format across any manufacturer or manual.
    Falls back to _DTC_CODE_RE when known_codes is empty or not supplied.
    """
    v = value.strip()
    if known_codes and v in known_codes:
        return True
    return bool(_DTC_CODE_RE.match(v) or _STEP_NUM_RE.match(v))


def _column_stats(data_rows: list, n_cols: int) -> list:
    """
    Compute per-column statistics across all data rows.

    Each entry:
        idx        — column index
        values     — one value per data row ('' when row is short)
        nonempty   — only the non-empty values
        unique     — deduplicated non-empty values (order-preserving)
        fill_ratio — fraction of data rows that have a non-empty value
    """
    stats = []
    for i in range(n_cols):
        vals     = [(row[i] if i < len(row) else '') for row in data_rows]
        nonempty = [v for v in vals if v]
        unique   = list(dict.fromkeys(nonempty))
        stats.append({
            "idx":        i,
            "values":     vals,
            "nonempty":   nonempty,
            "unique":     unique,
            "fill_ratio": len(nonempty) / len(data_rows) if data_rows else 0.0,
        })
    return stats


def _shared_confidence(s: dict) -> float:
    """
    How confident are we that this column is a shared field (PDF merged-cell)?

    1.0 — exactly one non-empty value in the entire column (true merged cell).
    0.8 — multiple rows but all carry the same value (PDF may have copied the cell).
    0.0 — more than one distinct value; column is not shared.
    """
    if not s["unique"]:
        return 0.0
    if len(s["unique"]) == 1:
        return 1.0 if len(s["nonempty"]) == 1 else 0.8
    return 0.0


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


_ALPHA_RE = re.compile(r'^[A-Za-z\s]+$')   # purely alphabetic label (no digits)


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


# Canonical column names for well-known table roles.
# Used as a fallback header when the PDF does not include a text header row
# (e.g. DTC codes start at row 0 with no label row above them).
_CANONICAL_HEADERS = {
    "dtc_logic": ["dtc", "trouble_diagnosis_name", "dtc_detecting_condition", "possible_causes"],
}


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

      "Module"  + "Connector"    → "Module Connector"   (slugified: module_connector)
      ""        + "Terminal No." → "Terminal No."
      "Existed" + ""             → "Existed"
      ""        + ""             → ""                   (slugified: col)
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


def _detect_primary_key(stats: list, known_codes: set | None = None) -> int | None:
    """
    Return the column index most likely to be the primary identifier.

    Criteria: all non-empty values are unique AND fill_ratio >= 0.8.
    Among qualifying columns, prefer the one whose values match strong
    identifiers (DTC codes, step numbers).  Falls back to leftmost match.
    """
    best_idx      = None
    best_strong   = False

    for s in stats:
        ne = len(s["nonempty"])
        if ne < 1:
            continue
        is_unique_key = (len(s["unique"]) == ne and s["fill_ratio"] >= 0.8)
        if not is_unique_key:
            continue
        has_strong = any(_is_strong_identifier(v, known_codes) for v in s["nonempty"])
        if best_idx is None:
            best_idx    = s["idx"]
            best_strong = has_strong
        elif has_strong and not best_strong:
            best_idx    = s["idx"]
            best_strong = True
            break   # strong-identifier column found — stop

    return best_idx


def _detect_sparse_key(data_rows: list, n_cols: int, known_codes: set | None = None) -> int | None:
    """
    Find the column index most likely to mark group boundaries in a
    grouped-rows table (sparse fill = one label per group of rows).

    Priority 1 — leftmost column whose non-empty values are strong identifiers.
    Priority 2 — leftmost sparsely-filled column (15–85% non-empty).
    """
    if not data_rows:
        return None
    n_rows = len(data_rows)

    strong_counts   = [0] * n_cols
    nonempty_counts = [0] * n_cols

    for row in data_rows:
        for i, val in enumerate(row):
            if i >= n_cols:
                break
            if val:
                nonempty_counts[i] += 1
                if _is_strong_identifier(val, known_codes):
                    strong_counts[i] += 1

    for i in range(n_cols):
        if strong_counts[i] > 0:
            return i

    for i in range(n_cols):
        ratio = nonempty_counts[i] / n_rows if n_rows else 0
        if 0.15 <= ratio <= 0.85:
            return i

    return None


def _detect_carry_forward_cols(data_rows: list, key_col_idx: int) -> set:
    """
    Return column indices that should carry forward within groups.

    A column is a carry-forward candidate when, within at least one group:
    - it is non-empty in the group-start row, AND
    - at least one continuation row in that group leaves it empty.

    This matches PDF merged-cell behaviour where a connector name (e.g. "LB9")
    appears only in the first row of a group and is blank below it.
    """
    candidates   = set()
    group_filled = set()
    in_group     = False

    for row in data_rows:
        is_group_start = bool(row[key_col_idx]) if key_col_idx < len(row) else False

        if is_group_start:
            group_filled = {i for i, v in enumerate(row) if v and i != key_col_idx}
            in_group = True
        elif in_group:
            for i in group_filled:
                if i >= len(row) or not row[i]:
                    candidates.add(i)

    return candidates


def _is_placeholder_header_cell(cell: str) -> bool:
    """Return True if a header cell is empty, dash-only, or symbol-only (placeholder)."""
    v = cell.strip()
    if not v:
        return True
    if re.match(r'^[-—–\s]+$', v):
        return True
    if not re.search(r'[a-zA-Z0-9]', v):
        return True
    return False


def _collect_quality_flags(
    raw_rows: list,
    n_header: int,
    header_cells: list,
    data_rows: list,
    known_codes: set | None = None,
) -> list[str]:
    """
    Inspect table structure and return quality flag strings for suspicious patterns.

    Flags (included only when the condition is met):
      multi_row_header_detected     — header spans 2 rows
      merged_header_cells_detected  — a row0 cell spans across a row1 gap position
      placeholder_header_detected   — a header cell is empty, dash-only, or symbol-only
      suspicious_normalized_headers — column slugs are generic ("col") or duplicated
      repeated_header_row_detected  — a data row closely matches the header row content
    """
    flags: list[str] = []

    # 1. Multi-row header
    if n_header == 2:
        flags.append("multi_row_header_detected")

    # 2. Merged header cells — row0 has a value where row1 is empty (spanning cell)
    if n_header == 2 and len(raw_rows) >= 2:
        row0 = raw_rows[0]
        row1 = raw_rows[1]
        n = max(len(row0), len(row1))
        for i in range(n):
            a = str(row0[i]).strip() if i < len(row0) else ''
            b = str(row1[i]).strip() if i < len(row1) else ''
            if a and not b:
                flags.append("merged_header_cells_detected")
                break

    # 3. Placeholder header cell (empty, dash-only, symbol-only)
    for cell in header_cells:
        if _is_placeholder_header_cell(str(cell)):
            flags.append("placeholder_header_detected")
            break

    # 4. Suspicious normalized headers — generic slugs or duplicates before deduplication
    seen_slugs: dict[str, int] = {}
    for cell in header_cells:
        slug = _slugify(cell) if (cell and str(cell).strip()) else "col"
        seen_slugs[slug] = seen_slugs.get(slug, 0) + 1
    if any(k == "col" for k in seen_slugs) or any(v > 1 for v in seen_slugs.values()):
        flags.append("suspicious_normalized_headers")

    # 5. Repeated header row — a data row closely matches the original header row
    if n_header >= 1 and raw_rows and data_rows:
        orig_header = [str(c).strip().lower() for c in raw_rows[0]]
        for row in data_rows:
            row_lower = [str(c).strip().lower() for c in row]
            n = max(len(orig_header), len(row_lower))
            padded_h = (orig_header + [''] * n)[:n]
            padded_r = (row_lower + [''] * n)[:n]
            total_h = sum(1 for a in padded_h if a)
            matches = sum(1 for a, b in zip(padded_h, padded_r) if a and a == b)
            if total_h > 0 and matches / total_h >= 0.5:
                flags.append("repeated_header_row_detected")
                break

    return flags


def _analyze_table(raw_rows: list, role: str | None = None, known_codes: set | None = None) -> dict:
    """
    Analyze a raw table and produce a semantic_parse result.
    Never modifies raw_rows.

    Detects three table structures:

    shared_fields — one shared description applies to multiple identifiers.
        Primary key column has all-unique, high-fill values.
        Shared columns have exactly one distinct value for the whole table.
        Output: primary_key_values, shared dict, individual list.

    grouped_rows — groups of rows share connector/label values via merged cells.
        Sparse key column marks group boundaries (DTC code, step number, etc.).
        Carry-forward columns are set once at group start and blank in continuation
        rows; they become group-level attributes.
        Output: key_column, header, groups (each group has its carry-forward fields
        at the top level and a nested connections list for the per-row data).

    flat — no detectable structure.
        Output: header, rows (plain dicts).

    Header detection runs before structure detection.  Multi-row headers
    (e.g. "Module" / "Connector" spanning two rows) are merged into compound
    keys ("module_connector") and the sub-header row is excluded from data.

    Status:
        "ok"      — structure confidently detected.
        "partial" — header found but no group/shared structure detected.
        "failed"  — no usable header or fewer than 2 rows.
    """
    FAILED = {"status": "failed", "table_type": None, "header": [], "rows": []}

    if not raw_rows or len(raw_rows) < 2:
        return FAILED

    # ── Detect header row count ───────────────────────────────────────────────
    # Guard: if row 0 contains DTC codes it is a data row, not a header.
    # DTC codes (P303D, P338A, etc.) are values — they must never become
    # column names.  Use canonical headers for known roles; fail otherwise.
    n_header = 0  # 0 = canonical fallback used (no text header row in the PDF)
    if _row_has_dtc_codes(raw_rows[0], known_codes):
        canonical = _CANONICAL_HEADERS.get(role)
        if canonical:
            # All rows are data — use the known column names instead
            header_cells = list(canonical)
            data_rows    = raw_rows
        else:
            return FAILED
    else:
        n_header = _detect_header_rows(raw_rows, known_codes)
        if n_header == 2:
            header_cells = _merge_header_rows(raw_rows[0], raw_rows[1])
        else:
            header_cells = list(raw_rows[0])
        data_rows = raw_rows[n_header:]

    if not data_rows:
        return FAILED

    if not any(c and str(c).strip() for c in header_cells):
        return FAILED

    # ── Build deduplicated snake_case header keys ─────────────────────────────
    seen: dict[str, int] = {}
    keys = []
    for cell in header_cells:
        slug  = _slugify(cell) if (cell and str(cell).strip()) else "col"
        count = seen.get(slug, 0) + 1
        seen[slug] = count
        keys.append(f"{slug}_{count}" if count > 1 else slug)

    n_cols = len(keys)
    stats  = _column_stats(data_rows, n_cols)

    # ── Collect quality flags ─────────────────────────────────────────────────
    quality_flags = _collect_quality_flags(raw_rows, n_header, header_cells, data_rows, known_codes)

    # ── Try: shared_fields ────────────────────────────────────────────────────
    pk_idx = _detect_primary_key(stats, known_codes)

    shared_cols: dict[str, dict] = {}
    if pk_idx is not None:
        for s in stats:
            if s["idx"] == pk_idx:
                continue
            conf = _shared_confidence(s)
            if conf > 0.0 and s["unique"]:
                shared_cols[keys[s["idx"]]] = {
                    "value":      s["unique"][0],
                    "confidence": conf,
                }

    # Only promote to shared_fields when at least one column is a true global
    # merged cell — appears in exactly one row (confidence 1.0).
    # Columns that repeat the same value once per group (confidence 0.8) are
    # carry-forward candidates in grouped_rows, not globally shared fields.
    has_true_shared = any(v["confidence"] >= 1.0 for v in shared_cols.values())

    if pk_idx is not None and shared_cols and has_true_shared:
        pk_name   = keys[pk_idx]
        pk_values = [v for v in stats[pk_idx]["values"] if v]

        shared_names    = set(shared_cols.keys())
        individual_idxs = [
            s["idx"] for s in stats
            if s["idx"] != pk_idx and keys[s["idx"]] not in shared_names
        ]

        individual = []
        for row in data_rows:
            padded = (list(row) + [''] * n_cols)[:n_cols]
            if not padded[pk_idx]:
                continue
            rec = {pk_name: padded[pk_idx]}
            for idx in individual_idxs:
                rec[keys[idx]] = padded[idx]
            individual.append(rec)

        result = {
            "status":             "ok" if not quality_flags else "partial",
            "table_type":         "shared_fields",
            "primary_key":        pk_name,
            "primary_key_values": pk_values,
            "shared":             shared_cols,
            "individual":         individual,
        }
        if quality_flags:
            result["quality_flags"] = quality_flags
            result["raw_rows_preferred"] = True
        return result

    # ── Try: grouped_rows ─────────────────────────────────────────────────────
    sparse_idx = _detect_sparse_key(data_rows, n_cols, known_codes)
    carry_cols = (
        _detect_carry_forward_cols(data_rows, sparse_idx)
        if sparse_idx is not None
        else set()
    )

    if sparse_idx is not None and carry_cols:
        key_name   = keys[sparse_idx]
        carry_idxs = sorted(carry_cols)
        # Columns that vary per row (not the key, not carry-forward)
        conn_idxs  = [i for i in range(n_cols) if i != sparse_idx and i not in carry_cols]

        groups   = []
        current  = None

        for row in data_rows:
            padded         = (list(row) + [''] * n_cols)[:n_cols]
            is_group_start = bool(padded[sparse_idx])

            if is_group_start:
                if current is not None:
                    groups.append(current)
                # New group: key value + carry-forward values from this row
                current = {key_name: padded[sparse_idx]}
                for idx in carry_idxs:
                    if padded[idx]:
                        current[keys[idx]] = padded[idx]
                current["connections"] = []

            if current is not None:
                conn = {keys[idx]: padded[idx] for idx in conn_idxs}
                current["connections"].append(conn)

        if current is not None:
            groups.append(current)

        result = {
            "status":     "ok" if not quality_flags else "partial",
            "table_type": "grouped_rows",
            "key_column": key_name,
            "header":     keys,
            "groups":     groups,
        }
        if quality_flags:
            result["quality_flags"] = quality_flags
            result["raw_rows_preferred"] = True
        return result

    # ── Fallback: flat ────────────────────────────────────────────────────────
    flat_rows = []
    for row in data_rows:
        padded = (list(row) + [''] * n_cols)[:n_cols]
        flat_rows.append(dict(zip(keys, padded)))

    result = {
        "status":             "partial",
        "raw_rows_preferred": True,
        "table_type":         "flat",
        "header":             keys,
        "rows":               flat_rows,
    }
    if quality_flags:
        result["quality_flags"] = quality_flags
    return result


def _make_record_id(document_id: str, start_pdf_page: int) -> str:
    """
    Generate a unique, deterministic ID for a DTC record.
    SHA256 of (document_id + start_pdf_page) — same PDF + same page = same ID.
    Truncated to 16 hex chars for readability.
    """
    raw = f"{document_id}{start_pdf_page}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def extract_records(pdf_path: Path, output_dir: Path) -> dict:
    """
    Main function called by pipeline.py.
    Returns one document-level JSON object for this PDF.
    output_dir is where image files will be saved.
    """
    source = pdf_path.name

    # SHA256 of the raw PDF bytes — same file different name = same ID
    document_id = hashlib.sha256(pdf_path.read_bytes()).hexdigest()

    # ── Profile the PDF ───────────────────────────────────────────────────────
    metadata, pdf_profile = profile_pdf(pdf_path)

    # ── Extract vehicle info ──────────────────────────────────────────────────
    vehicle = extract_vehicle_info(pdf_path, metadata)

    # ── Build DTC index ───────────────────────────────────────────────────────
    index = build_index(pdf_path)

    if not index:
        print("No codes found.")
        return {}

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

    records     = []
    seen_xrefs  = set()
    seen_hashes = {}

    for record_num, (page_num, codes) in enumerate(sorted(page_to_codes.items()), start=1):
        print(f"  Page {page_num} -> {codes}")

        page_ref_base = f"{pdf_path.stem}-{page_num}"

        content = extract_content(
            pdf_path, page_num, codes, output_dir,
            page_ref_base, seen_xrefs, seen_hashes
        )

        # ── Cross-check: index ref vs footer ref ──────────────────────────────
        index_ref  = page_to_ref.get(page_num)
        footer_ref = content["start_page_ref_footer"]
        warnings   = []
        if index_ref and footer_ref and index_ref != footer_ref:
            msg = f"page_ref mismatch on PDF page {page_num}: index={index_ref}, footer={footer_ref}"
            print(f"  [WARN] {msg}")
            warnings.append(msg)

        # ── page_refs list ────────────────────────────────────────────────────
        # Full ordered list of footer labels seen across all pages of this block.
        page_refs    = content["page_refs"]
        section_code = content.get("section_code")

        # ── DTC title ─────────────────────────────────────────────────────────
        dtc_title = _normalize_title(codes, code_titles)

        # ── Sections — assign section_id to each ─────────────────────────────
        sections = []
        for s_idx, sec in enumerate(content["sections"]):
            sections.append({
                "section_id": f"r{record_num}_s{s_idx + 1}",
                "heading":    sec["heading"],
                "role":       sec["role"],
                "text":       sec["text"],
                "page_start": sec["page_start"],
                "page_end":   sec["page_end"],
            })

        # ── Tables — flat list, each linked to its section via section_id ─────
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
                })
                t_count += 1

        # Detect cross-page continuations → table_groups (raw tables unchanged)
        table_groups, absorbed_ids = _merge_continued_tables(tables, notes, record_num)

        # Finalize raw tables: rename location fields, pop rows → raw_rows.
        # Semantic parse only for standalone tables not absorbed into a group.
        for tbl in tables:
            raw    = tbl.pop("rows")
            page   = tbl.pop("page")
            pr     = tbl.pop("page_ref")
            tbl["start_pdf_page"] = page
            tbl["end_pdf_page"]   = page
            tbl["page_refs"]      = [pr] if pr else []
            tbl["raw_rows"]       = raw
            if tbl["table_id"] not in absorbed_ids:
                tbl["semantic_parse"] = _analyze_table(
                    raw, role=tbl.get("role"), known_codes=set(codes)
                )

        # Semantic parse on table_groups (complete merged rows)
        for grp in table_groups:
            grp["semantic_parse"] = _analyze_table(
                grp["raw_rows"], role=grp.get("role"), known_codes=set(codes)
            )

        # ── Images — enriched with metadata ──────────────────────────────────
        images = []
        for i_idx, img in enumerate(content["image_list"]):
            images.append({
                "image_id":   f"r{record_num}_i{i_idx + 1}",
                "section_id": None,          # not yet assigned to a specific section
                "pdf_page":   img["pdf_page"],
                "page_ref":   img["page_ref"],
                "image_path": f"images/{img['filename']}",
                "caption":    None,
                "role":       "unknown",
            })

        records.append({
            "record_id":   _make_record_id(document_id, page_num),
            "record_type": "dtc_block",

            "codes": codes,
            "title": dtc_title,

            "location": {
                "start_pdf_page": page_num,
                "end_pdf_page":   content["end_pdf_page"],
                "page_refs":      page_refs,
                **({"section_code": section_code} if section_code else {}),
            },

            "sections":     sections,
            "tables":       tables,
            "table_groups": table_groups,
            "images":       images,
            "notes":        notes,

            "raw_text": content["raw_text"],

            "extraction": {
                "status":   "success",
                "ocr_used": False,
                "warnings": warnings,
            },
        })

    return {
        "schema_version": 4,
        "document_id":    document_id,
        "source_file":    source,
        "metadata":       metadata,
        "pdf_profile":    pdf_profile,
        "vehicle":        vehicle,
        "records":        records,
    }
