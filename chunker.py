"""
chunker.py — semantic chunking
Reads:  classified/*.json  (all batches processed as one continuous stream)
Writes: chunks.json

One chunk = one complete procedure unit.
chunk_type values:
  precaution  — safety briefing pages, no numbered steps
  procedure   — numbered steps with optional warnings
  description — system description, component parts, no steps

Key fixes:
  - Tables assigned to ONE chunk only (first chunk that claims them)
  - Cross-page tables merged before chunking — e.g. HA-34 and HA-35
    are one logical table split across two pages
  - Vehicle variant extracted cleanly from footer text
  - Image ref codes cleaned from table cells
"""

from __future__ import annotations
import json, logging, re
from pathlib import Path

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S", level=logging.INFO)
log = logging.getLogger("chunker")

_PREREQ_RE      = re.compile(r"\b(before|prior to|ensure|verify|confirm|check that|must be)\b", re.IGNORECASE)
_SAFETY_ORDER   = {"HIGH_VOLTAGE": 3, "WARNING": 2, "CAUTION": 1, "NONE": 0}
_VARIANT_RE     = re.compile(r"\b(\d{4}\s+Leaf(?:\s+\w+)?)\b", re.IGNORECASE)
_IMG_REF_INLINE = re.compile(r"\s*\b[A-Z]{2,5}\d{3,6}[A-Z]{0,3}\b")
_TOC_SUFFIX_RE  = re.compile(r"\s*\.{3,}[\d\s]*$")   # strips "......5" tails from TOC headings
_MIN_IMG_DIM    = 20  # PDF points — bbox smaller than this in either axis is an icon/bullet


# ── Helpers ───────────────────────────────────────────────────────────────────

def _highest_safety(elements: list[dict]) -> str:
    best = "NONE"
    for el in elements:
        level = el.get("safety_level") or "NONE"
        if _SAFETY_ORDER.get(level, 0) > _SAFETY_ORDER.get(best, 0):
            best = level
    return best


def _detect_chunk_type(elements: list[dict]) -> str:
    types = [el.get("type") for el in elements]
    has_steps    = "procedure_step" in types
    has_warnings = "warning" in types or "warning_header" in types
    has_text     = any(t in ("general_text", "spec_value") for t in types)

    if has_steps:
        return "procedure"
    if has_warnings and not has_steps and not has_text:
        return "precaution"
    return "description"


def _extract_prerequisites(elements: list[dict]) -> list[str]:
    prereqs = []
    first_step_idx = next(
        (i for i, el in enumerate(elements) if el.get("type") == "procedure_step"),
        len(elements)
    )
    for el in elements[:first_step_idx]:
        if el.get("type") == "warning" and el["text"].strip() not in prereqs:
            prereqs.append(el["text"].strip())
    for el in elements[:5]:
        text = el.get("text", "")
        if _PREREQ_RE.search(text) and text.strip() not in prereqs:
            prereqs.append(text.strip())
    return prereqs


def _extract_variant(extraction: dict) -> str | None:
    vehicle_raw = extraction.get("vehicle")
    if vehicle_raw:
        match = _VARIANT_RE.search(str(vehicle_raw))
        if match:
            return match.group(1).strip()
    page_map = extraction.get("page_map", {})
    for val in page_map.values():
        if isinstance(val, list):
            for v in val:
                if v:
                    match = _VARIANT_RE.search(str(v))
                    if match:
                        return match.group(1).strip()
    return None


def _clean_table_cell(cell: str) -> str:
    return _IMG_REF_INLINE.sub("", cell).strip()


def _grid_to_markdown(grid: list[list[str]]) -> str:
    """Build markdown string from grid — always reflects current data."""
    if not grid:
        return ""
    header = "| " + " | ".join(grid[0]) + " |"
    sep    = "| " + " | ".join(["---"] * len(grid[0])) + " |"
    rows   = ["| " + " | ".join(row) + " |" for row in grid[1:]]
    return "\n".join([header, sep] + rows)


def _clean_table(table: dict) -> dict:
    grid = table.get("data", [])
    if not grid:
        return table
    cleaned = [[_clean_table_cell(cell) for cell in row] for row in grid]
    return {
        **table,
        "data":     cleaned,
        "num_rows": len(cleaned),
        "markdown": _grid_to_markdown(cleaned),
    }


def _headers_match(row_a: list[str], row_b: list[str]) -> bool:
    """
    Check if two header rows are the same — used to detect cross-page tables.
    Compares lowercased stripped values so minor whitespace differences don't matter.
    """
    if len(row_a) != len(row_b):
        return False
    return all(a.strip().lower() == b.strip().lower() for a, b in zip(row_a, row_b))


def _merge_cross_page_tables(tables: list[dict]) -> list[dict]:
    """
    CROSS-PAGE TABLE MERGING — new function.

    When a table is too tall to fit on one page, Docling extracts it as two
    separate table objects — one per page. For example HA-34 and HA-35 are
    one logical symptom table split across two pages.

    Detection: two consecutive tables in the same section with matching
    header rows. Adapted from coworker's DTC pipeline logic.

    What it does:
      - Loops through all tables in page order
      - If the next table has the same section_code AND matching headers
        → append its data rows (skipping its header) to the current table
      - Records all page references the merged table spans
      - Marks merged tables as used so they don't appear twice
    """
    if not tables:
        return tables

    merged = []
    skip: set[int] = set()

    for i, tbl in enumerate(tables):
        if i in skip:
            continue

        combined = {**tbl}
        combined["data"] = [row[:] for row in tbl.get("data", [])]
        pages_merged = [tbl.get("page_manual") or str(tbl.get("page_pdf", ""))]

        for j in range(i + 1, len(tables)):
            if j in skip:
                continue

            nxt = tables[j]

            # Must be same section and both must have data with matching headers
            same_section = nxt.get("section_code") == tbl.get("section_code")
            has_data     = bool(combined["data"]) and bool(nxt.get("data"))
            headers_ok   = has_data and _headers_match(
                combined["data"][0], nxt["data"][0]
            )

            if same_section and headers_ok:
                # Append rows from next table, skipping its header row
                combined["data"].extend(nxt["data"][1:])
                pages_merged.append(nxt.get("page_manual") or str(nxt.get("page_pdf", "")))
                combined["num_rows"] = len(combined["data"])
                skip.add(j)
            else:
                break  # only merge consecutive tables

        combined["pages_merged"] = pages_merged
        combined["num_rows"]     = len(combined["data"])
        combined["markdown"]     = _grid_to_markdown(combined["data"])
        merged.append(combined)

    if len(merged) < len(tables):
        log.info("  merged %d cross-page tables → %d tables",
                 len(tables), len(merged))

    return merged


def _chunk_id(section_code: str | None, page_pdf: int | None, index: int) -> str:
    return f"{section_code or 'UNK'}_pdf{page_pdf or 0}_chunk{index}"


# ── Load all batches as one ordered stream ────────────────────────────────────

def _load_all(classified_dir: Path) -> tuple[list[dict], list[dict], list[dict], str | None]:
    files = sorted(
        classified_dir.glob("*.json"),
        key=lambda p: int(p.stem.split("_")[0])
    )
    if not files:
        log.error("No classified JSON files found in %s", classified_dir)
        return [], [], [], None

    texts, tables, images = [], [], []
    variant = None

    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        texts.extend(data.get("text_elements", []))
        tables.extend(data.get("tables", []))
        images.extend(data.get("images", []))
        if not variant:
            extraction = data.get("extraction", {})
            variant = _extract_variant(extraction)

    log.info("Loaded %d elements  %d tables  %d images  from %d batches  variant=%s",
             len(texts), len(tables), len(images), len(files), variant)
    return texts, tables, images, variant


def _page_lookup(items: list[dict]) -> dict[int, list[dict]]:
    lookup: dict[int, list[dict]] = {}
    for item in items:
        pg = item.get("page_pdf")
        if pg is not None:
            lookup.setdefault(pg, []).append(item)
    return lookup


# ── Core chunker ──────────────────────────────────────────────────────────────

def _build_chunks(
    texts:        list[dict],
    table_lookup: dict[int, list[dict]],
    image_lookup: dict[int, list[dict]],
    variant:      str | None,
) -> list[dict]:
    chunks:          list[dict] = []
    idx:             int        = 0
    current_els:     list[dict] = []
    current_pages:   set[int]   = set()
    last_hv_prereqs: list[str]  = []

    used_tables: set[tuple] = set()
    used_images: set[tuple] = set()

    heading      = "PREAMBLE"
    section_code = None
    page_pdf     = None
    page_manual  = None

    def _flush():
        nonlocal idx, last_hv_prereqs
        if not current_els and not current_pages:
            return

        chunk_tables = []
        for pg in sorted(current_pages):
            for t in table_lookup.get(pg, []):
                # Skip TOC tables — not useful for the agent
                if t.get("table_type") == "toc":
                    continue
                t_key = (t.get("page_pdf"), str(t.get("bbox")))
                if t_key not in used_tables:
                    used_tables.add(t_key)
                    chunk_tables.append(_clean_table(t))

        chunk_images = []
        for pg in sorted(current_pages):
            for img in image_lookup.get(pg, []):
                bbox = img.get("bbox") or []
                if len(bbox) == 4:
                    if (abs(bbox[2] - bbox[0]) < _MIN_IMG_DIM
                            or abs(bbox[3] - bbox[1]) < _MIN_IMG_DIM):
                        continue
                i_key = (img.get("page_pdf"), str(img.get("bbox")))
                if i_key not in used_images:
                    used_images.add(i_key)
                    chunk_images.append(img)

        chunk_type = _detect_chunk_type(current_els)
        safety     = _highest_safety(current_els)
        prereqs    = _extract_prerequisites(current_els)

        # Inherit HV prerequisites from the preceding safety section when a
        # sub-procedure chunk doesn't repeat the warning locally.
        if safety == "HIGH_VOLTAGE" and not prereqs and last_hv_prereqs:
            prereqs = last_hv_prereqs[:]
        if safety == "HIGH_VOLTAGE" and prereqs:
            last_hv_prereqs = prereqs[:]

        chunks.append({
            "chunk_id":      _chunk_id(section_code, page_pdf, idx),
            "chunk_type":    chunk_type,
            "page_pdf":      page_pdf,
            "page_manual":   page_manual,
            "section_code":  section_code,
            "vehicle":       variant,
            "heading":       heading,
            "safety_level":  safety,
            "prerequisites": prereqs,
            "text_blocks":   current_els[:],
            "tables":        chunk_tables,
            "images":        chunk_images,
        })

        idx += 1
        current_els.clear()
        current_pages.clear()

    for el in texts:
        pg = el.get("page_pdf")
        if el.get("type") == "section_header":
            _flush()
            heading      = _TOC_SUFFIX_RE.sub("", el.get("text", "").strip()).strip()
            section_code = el.get("section_code")
            page_pdf     = pg
            page_manual  = el.get("page_manual")

        current_els.append(el)
        if pg is not None:
            current_pages.add(pg)

    _flush()
    return chunks


# ── Entry point ───────────────────────────────────────────────────────────────

def run(
    classified_dir: str | Path = "classified",
    output_file:    str | Path = "chunks.json",
) -> bool:
    classified_dir = Path(classified_dir)
    output_file    = Path(output_file)

    texts, tables, images, variant = _load_all(classified_dir)
    if not texts:
        return False

    # Merge cross-page tables BEFORE building page lookup
    # This ensures HA-34 + HA-35 become one table before chunks are assigned
    tables = _merge_cross_page_tables(tables)

    chunks = _build_chunks(texts, _page_lookup(tables), _page_lookup(images), variant)

    hv          = sum(1 for c in chunks if c["safety_level"] == "HIGH_VOLTAGE")
    w_tables    = sum(1 for c in chunks if c["tables"])
    w_images    = sum(1 for c in chunks if c["images"])
    w_prereq    = sum(1 for c in chunks if c["prerequisites"])
    procedures  = sum(1 for c in chunks if c["chunk_type"] == "procedure")
    precautions = sum(1 for c in chunks if c["chunk_type"] == "precaution")

    log.info(
        "chunks=%d  procedures=%d  precautions=%d  hv=%d  "
        "with_tables=%d  with_images=%d  with_prereqs=%d",
        len(chunks), procedures, precautions, hv, w_tables, w_images, w_prereq,
    )

    output_file.write_text(
        json.dumps({
            "schema_version": "1.0",
            "vehicle":        variant,
            "total_chunks":   len(chunks),
            "stats": {
                "high_voltage_chunks": hv,
                "procedure_chunks":    procedures,
                "precaution_chunks":   precautions,
                "chunks_with_tables":  w_tables,
                "chunks_with_images":  w_images,
                "chunks_with_prereqs": w_prereq,
            },
            "chunks": chunks,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    log.info("Written -> %s", output_file)
    return True


if __name__ == "__main__":
    run(classified_dir="classified", output_file="chunks.json") 