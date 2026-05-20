"""
section_classifier.py — Reconstruct manual as hierarchical section blocks
Reads:  output/{SECTION}_classified.json  (from classifier.py)
        raw/section_map.json              (from contents_parser.py)
Writes: output/{SECTION}_sectioned.json   (LLM-ready final output)

Design principle:
  One header = One section block. NOT one line = one object.

Each section node contains:
  - title, level, page_pdf range, manual_page range
  - merged_text: all text in this section AND all descendants, in reading order
  - tables: cleaned table objects (no bbox, no element_id)
  - images: cleaned image references
  - children: nested child sections (recursive)

What is REMOVED from output (stays in raw.json only):
  - bbox, element_id, top_y, coordinate systems
  - font metadata, reading_order, docling_label
  - raw text_elements arrays
  - merged_text_full (was causing duplication — removed entirely)

Coordinate system notes:
  PDF outline /Top  : Y from BOTTOM of page. Higher = higher on page.
  Docling bbox[1]   : Y from BOTTOM of page (PDF coords). Higher = higher on page.
  pymupdf bbox[1]   : Y from TOP of page. Lower = higher on page.
  _to_pdf_y()       : returns Docling bbox[1] unchanged (already PDF Y-from-bottom).

Assignment rules (all same-page boundary checks):
  - Element is BELOW section start if el_pdf_y < section.top_y_start
    (element Y from bottom is less than section heading Y from bottom)
    -> excluded from this section
  - Element is AT OR BELOW section end if el_pdf_y <= section.top_y_end
    -> excluded from this section (belongs to next section)
  - When multiple sections at same depth qualify on same page,
    pick the one whose top_y_start is closest to (and <= ) el_pdf_y
    i.e. the section heading that is closest above the element.
"""

from __future__ import annotations
import json, logging, re
from collections import Counter
from pathlib import Path

import config

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger("section_classifier")

# Actual HA PDF page height confirmed: 792 pts
PDF_PAGE_HEIGHT = 792.0

# Minimum outline level to assign elements to.
# L0 and L1 are structural containers (Table of Contents, WITH HEAT PUMP SYSTEM)
# that span the entire document — do not assign content to them.
MIN_ASSIGNMENT_LEVEL = 2


# ── Coordinate conversion ─────────────────────────────────────────────────────

def _to_pdf_y(bbox: list | None) -> float | None:
    """
    Return Docling bbox[1] as PDF Y coordinate (Y from bottom of page).
    Docling stores b.t in PDF coordinates (Y from bottom), so no conversion needed.
    Higher value = higher on page.
    Returns None if bbox is missing or malformed.
    """
    if not bbox or len(bbox) < 2:
        return None
    return float(bbox[1])


# ── Section tree utilities ────────────────────────────────────────────────────

def _flatten(nodes: list[dict], results: list | None = None) -> list[dict]:
    """Flatten nested section tree into ordered list."""
    if results is None:
        results = []
    for node in nodes:
        results.append(node)
        _flatten(node.get("children", []), results)
    return results


def _find_node(nodes: list[dict], node_id: str) -> dict | None:
    """Find a section node by id in the tree."""
    for n in nodes:
        if n["section_id"] == node_id:
            return n
        found = _find_node(n.get("children", []), node_id)
        if found:
            return found
    return None


def _flat_for_assignment(nodes: list[dict], min_level: int = MIN_ASSIGNMENT_LEVEL) -> list[dict]:
    """
    Flatten tree keeping only fields needed for assignment.
    Excludes sections below min_level (default: MIN_ASSIGNMENT_LEVEL).
    Pass min_level=0 to include L0/L1 structural containers as a fallback
    for content that lives on pages not covered by any L2+ section.
    """
    result = []
    def _walk(ns: list[dict]) -> None:
        for n in ns:
            if n["level"] >= min_level:
                loc = n.get("location", {})
                result.append({
                    "id":             n["section_id"],
                    "level":          n["level"],
                    "page_pdf_start": loc.get("start_pdf_page"),
                    "page_pdf_end":   loc.get("end_pdf_page"),
                    "top_y_start":    n.get("top_y_start"),
                    "top_y_end":      n.get("top_y_end"),
                })
            _walk(n.get("children", []))
    _walk(nodes)
    return result


# ── Element assignment ────────────────────────────────────────────────────────

def _belongs_to(el_page: int, el_pdf_y: float | None, sec: dict) -> bool:
    """
    Return True if element at (el_page, el_pdf_y) falls within section boundaries.

    Page range check: el_page must be within [page_pdf_start, page_pdf_end].

    Same-page Y checks (PDF coordinates, Y from bottom, higher = higher on page):

    Start page: element must be AT OR BELOW section heading.
      Section heading is at top_y_start.
      Element at pdf_y < top_y_start is above the heading -> does not belong.
      Note: element AT exactly top_y_start is the heading itself -> include.

    End page: element must be ABOVE section end boundary.
      Section end is defined by top_y_end (= start of next sibling section).
      Element at pdf_y <= top_y_end is at or below the next section start -> exclude.
      This ensures boundary elements go to the NEXT section, not the current one.
    """
    sp = sec.get("page_pdf_start")
    ep = sec.get("page_pdf_end")
    if sp is None or ep is None:
        return False
    if not (sp <= el_page <= ep):
        return False

    if el_pdf_y is not None:
        # Start page check.
        # PDF Y increases upward. Section heading is at top_y_start.
        # Content flows BELOW the heading = lower pdf_y values.
        # Exclude element if its pdf_y is GREATER than top_y_start
        # (element is above the section heading = before this section).
        if el_page == sp:
            sy = sec.get("top_y_start")
            if sy is not None and el_pdf_y > sy:
                return False   # element is above section heading

        # End page check.
        # Section ends at top_y_end (= start of next sibling section).
        # Exclude element if pdf_y <= top_y_end
        # (element is at or below the next section's heading = belongs to next section).
        if el_page == ep:
            ey = sec.get("top_y_end")
            if ey is not None and ey > 0 and el_pdf_y <= ey:
                return False   # element belongs to next section

    return True


def _find_best_section(
    el_page: int,
    el_pdf_y: float | None,
    flat: list[dict],
) -> str | None:
    """
    Find the section whose heading immediately precedes this element in reading order.

    Primary rule (when el_pdf_y is known and any candidate starts on el_page):
      Among sections that START on el_page, pick the one whose top_y_start is
      the smallest value that is still >= el_pdf_y.
      In Y-from-bottom coordinates that is the heading physically closest above
      the element — the section the element falls directly under, regardless of
      whether it is a parent, child, or sibling.

      Example with three headings on page 5:
        L2 "PRECAUTION"          top_y_start = 742
        L4 "OPERATION PROHIBIT"  top_y_start = 650
        element                  el_pdf_y    = 700
      → L4 is excluded by _belongs_to (700 > 650).
      → Only L2 qualifies; element goes to L2. ✓

      Example where element is below both headings (el_pdf_y = 620):
      → Both L2 (742) and L4 (650) qualify.
      → min(742, 650) = 650 → element goes to L4 (closest heading above). ✓

    Fallback (no Y, or element is on an interior page):
      Use the deepest (most specific) covering section.
    """
    candidates = [s for s in flat if _belongs_to(el_page, el_pdf_y, s)]
    if not candidates:
        return None

    # No Y position — use deepest level (covers tables/images too).
    if el_pdf_y is None:
        deepest_level = max(s["level"] for s in candidates)
        deepest = [s for s in candidates if s["level"] == deepest_level]
        return deepest[0]["id"]

    # Sections that START on this page — heading immediately above the element.
    # _belongs_to already excluded sections whose heading is below the element
    # (el_pdf_y > top_y_start → False), so all same-page candidates have
    # top_y_start >= el_pdf_y.  Smallest top_y_start = closest above.
    same_page = [s for s in candidates if s.get("page_pdf_start") == el_page]
    if same_page:
        return min(
            same_page,
            key=lambda s: s["top_y_start"] if s.get("top_y_start") is not None else float("inf"),
        )["id"]

    # Interior page — no section starts here; use deepest covering section.
    deepest_level = max(s["level"] for s in candidates)
    deepest = [s for s in candidates if s["level"] == deepest_level]
    return deepest[0]["id"]


# ── Text merging ──────────────────────────────────────────────────────────────

_MULTI_NEWLINE = re.compile(r"\n{3,}")
_BROKEN_WRAP   = re.compile(r"(?<=[a-z,])\n(?=[a-z])")


def _clean_text(text: str) -> str:
    text = _BROKEN_WRAP.sub(" ", text)
    text = _MULTI_NEWLINE.sub("\n\n", text)
    return text.strip()


def _build_merged_text(elements: list[dict]) -> str:
    """
    Merge direct text elements into one string in reading order.

    Sort: page_pdf first, then reading_order if populated, then bbox[1] descending
    (bbox[1] is Y-from-bottom; negated so ascending sort = top-to-bottom reading order).

    Known limitation: Docling currently returns reading_order=None for all elements,
    so sort falls back to Y position. For pages where the PDF content stream order
    does not match visual order (e.g. bullet lists extracted before preceding text),
    the merged_text order may not perfectly match the printed page. Content is
    complete and correct — only ordering within a section may occasionally differ.

    Texts appearing 5+ times identically (running headers/footers) are filtered.
    Threshold is 5 (not 3) to avoid suppressing section titles that appear in
    the TOC, a running header, and once in the body (3 occurrences = real content).
    """
    def sort_key(el: dict):
        pg = el.get("page_pdf") or 0
        ro = el.get("reading_order")
        if ro is not None:
            return (pg, 0, int(ro), 0.0)
        bbox = el.get("bbox") or []
        # Negate Y-from-bottom so that ascending sort reads top-to-bottom.
        # bbox[1] = Docling b.t = Y from bottom; larger = higher on page.
        # Without negation, ascending sort produces bottom-to-top (reversed) order.
        y = -float(bbox[1]) if len(bbox) >= 2 else 9999.0
        return (pg, 1, 0, y)

    sorted_els = sorted(elements, key=sort_key)

    counts  = Counter(el.get("text", "").strip() for el in sorted_els)
    running = {t for t, n in counts.items() if n >= 5 and 0 < len(t) < 80}

    lines = []
    for el in sorted_els:
        text = (el.get("text") or "").strip()
        if not text:
            continue
        if text in running:
            continue
        lines.append(text)

    return _clean_text("\n".join(lines))


# ── Table and image cleaning ──────────────────────────────────────────────────

def _clean_table(tbl: dict) -> dict:
    # Classifier writes the full grid (header row first) into "data".
    # Do not slice — header and rows are already separated by classifier.
    return {
        "table_type":    tbl.get("table_type", "general"),
        "page_manual":   tbl.get("page_manual"),
        "num_rows":      tbl.get("num_rows", 0),
        "num_cols":      tbl.get("num_cols", 0),
        "headers":       (tbl.get("data") or [[]])[0],
        "data":          (tbl.get("data") or [])[1:],
        "markdown":      tbl.get("markdown", ""),
        "is_dtc":        tbl.get("is_dtc", False),
        "content_owner": tbl.get("content_owner"),
    }


def _clean_image(img: dict) -> dict:
    return {
        "file":           img.get("file"),
        "subtype":        img.get("subtype"),
        "page_manual":    img.get("page_manual"),
        "caption":        img.get("caption_raw") or "",
        "image_ref_code": img.get("image_ref_code"),
        "content_owner":  img.get("content_owner"),
    }


# ── Section tree initialisation ───────────────────────────────────────────────

def _make_node(raw: dict) -> dict:
    sp       = raw.get("page_pdf_start")
    ep       = raw.get("page_pdf_end")
    mp_start = raw.get("manual_page_start")
    mp_end   = raw.get("manual_page_end")
    page_refs = [r for r in [mp_start, mp_end] if r is not None]

    return {
        "section_id":  raw["id"],
        "record_type": "procedure_section",
        "title":       raw["title"],
        "level":       raw["level"],
        "location": {
            "start_pdf_page": sp,
            "end_pdf_page":   ep,
            "page_refs":      page_refs,
            "section_code":   None,   # stamped at write time from profile
        },
        "top_y_start":   raw.get("top_y_start"),   # internal — stripped before output
        "top_y_end":     raw.get("top_y_end"),     # internal — stripped before output
        "merged_text":   "",
        "element_count": 0,
        "tables":        [],
        "images":        [],
        "notes":         [],
        "extraction": {
            "status":   "success",
            "ocr_used": False,
            "warnings": [],
        },
        "_elements":  [],   # temporary — removed before output
        "children":   [],
    }


def _init_tree(raw_nodes: list[dict]) -> list[dict]:
    return [
        {**_make_node(n), "children": _init_tree(n.get("children", []))}
        for n in raw_nodes
    ]


# ── Finalise tree ─────────────────────────────────────────────────────────────

def _finalise(nodes: list[dict], section_code: str, ocr_used: bool) -> None:
    """
    Build merged_text, update element_count, stamp section_code,
    set ocr_used on extraction block, remove internal fields.

    merged_text rollup:
      Each node's merged_text is built from its own direct _elements first,
      then child merged_text blocks are appended in document order.
      This ensures a parent section (e.g. PRECAUTION) has a complete readable
      block even when all content was assigned to deep leaf children.
      The LLM agent querying any level of the hierarchy gets full text.
    """
    for node in nodes:
        # Build this node's own merged_text from direct elements
        node["merged_text"] = _build_merged_text(node.get("_elements", []))

        direct = (
            len(node.get("_elements", [])) +
            len(node.get("tables", [])) +
            len(node.get("images", []))
        )

        # Recursively finalise children first so their merged_text is ready
        _finalise(node.get("children", []), section_code, ocr_used)

        # Roll up child merged_text into parent so parent has complete content.
        # Children are already in document order from the section tree.
        # A mechanic querying PRECAUTION gets all text under it, not an empty string.
        child_texts = [
            c["merged_text"] for c in node.get("children", [])
            if c.get("merged_text")
        ]
        if child_texts:
            parts = ([node["merged_text"]] if node["merged_text"] else []) + child_texts
            node["merged_text"] = "\n\n".join(parts)

        child_count = sum(c.get("element_count", 0) for c in node.get("children", []))
        node["element_count"] = direct + child_count

        # Stamp section_code into location
        node["location"]["section_code"] = section_code

        # Stamp ocr_used from batch metadata
        node["extraction"]["ocr_used"] = ocr_used

        # Remove internal fields
        node.pop("_elements", None)
        node.pop("top_y_start", None)
        node.pop("top_y_end", None)


# ── Entry point ───────────────────────────────────────────────────────────────

def run(
    raw_dir:    str | Path = "raw",
    output_dir: str | Path = "output",
) -> bool:
    raw_dir    = Path(raw_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load section map
    section_map_path = raw_dir / "section_map.json"
    if not section_map_path.exists():
        log.error("section_map.json not found — run contents_parser.py first")
        return False
    section_map  = json.loads(section_map_path.read_text(encoding="utf-8"))
    section_code = section_map.get("section_code", "UNKNOWN")

    log.info("Section map: %d sections from %s",
             section_map.get("total_sections", 0), section_map.get("source"))

    # Load classified output
    classified_path = output_dir / f"{section_code}_classified.json"
    if not classified_path.exists():
        log.error("Classified file not found: %s", classified_path)
        return False
    classified = json.loads(classified_path.read_text(encoding="utf-8"))
    log.info("Classified: text=%d tables=%d images=%d",
             len(classified.get("text_elements", [])),
             len(classified.get("tables", [])),
             len(classified.get("images", [])))

    # Load shared profile
    profile_path = raw_dir / "shared_profile.json"
    profile      = {}
    if profile_path.exists():
        profile = json.loads(profile_path.read_text(encoding="utf-8"))

    raw_sections = section_map.get("sections", [])

    if not raw_sections:
        log.warning("Empty section map — writing unstructured output")
        _write_output(output_dir, section_code, profile, section_map, [], [])
        return True

    # Build section tree with empty element buckets
    tree     = _init_tree(raw_sections)
    flat     = _flat_for_assignment(tree)                # level >= 2  (text primary)
    flat_all = _flat_for_assignment(tree, min_level=0)   # all levels  (table/image fallback)

    log.info("Assigning elements to %d eligible sections (level >= %d)",
             len(flat), MIN_ASSIGNMENT_LEVEL)

    unassigned: list = []

    # ── Assign text elements ──────────────────────────────────────────────────
    for el in classified.get("text_elements", []):
        pg    = el.get("page_pdf")
        pdf_y = _to_pdf_y(el.get("bbox"))

        if pg is None:
            continue   # drop unlocatable elements silently

        sec_id = _find_best_section(pg, pdf_y, flat)
        if sec_id:
            node = _find_node(tree, sec_id)
            if node is not None:
                node["_elements"].append(el)

    # ── Assign tables ─────────────────────────────────────────────────────────
    # Tables use page-range assignment only (el_pdf_y=None) — no Y boundary
    # check.  Y precision is only needed for text on pages where multiple
    # sibling sections start; tables are large enough that page range suffices.
    #
    # Assignment order:
    #   1. Primary: find a level-2+ section (flat).
    #   2. Fallback: find any section including L0/L1 containers (flat_all).
    #      This ensures master TOC tables and other front-matter content are
    #      placed in their structural container rather than lost to unassigned.
    #   3. toc-typed tables are NOT silently discarded — they go to unassigned
    #      so they remain inspectable in the output.
    for tbl in classified.get("tables", []):
        pg = tbl.get("page_pdf")
        if pg is None:
            continue

        if tbl.get("table_type") == "toc":
            # Never silently discard TOC tables — preserve in unassigned.
            unassigned.append({"type": "table", "data": _clean_table(tbl)})
            continue

        sec_id = _find_best_section(pg, None, flat)
        if not sec_id:
            sec_id = _find_best_section(pg, None, flat_all)   # L0/L1 fallback

        if sec_id:
            node = _find_node(tree, sec_id)
            if node is not None:
                node["tables"].append(_clean_table(tbl))
                continue

        unassigned.append({"type": "table", "data": _clean_table(tbl)})

    # ── Assign images ─────────────────────────────────────────────────────────
    # Same page-range-only assignment as tables.
    # L0/L1 fallback applied for images on pre-section pages.
    for img in classified.get("images", []):
        if img.get("subtype") == "safety_icon":
            continue

        pg = img.get("page_pdf")
        if pg is None:
            continue

        sec_id = _find_best_section(pg, None, flat)
        if not sec_id:
            sec_id = _find_best_section(pg, None, flat_all)   # L0/L1 fallback

        if sec_id:
            node = _find_node(tree, sec_id)
            if node is not None:
                node["images"].append(_clean_image(img))
                continue

        unassigned.append({"type": "image", "data": _clean_image(img)})

    # ── Finalise: build merged_text, count elements, strip internal fields ────
    ocr_used = classified.get("batch", {}).get("ocr_used", False)
    _finalise(tree, section_code, ocr_used)

    # Stats
    all_nodes    = _flatten(tree)
    with_content = sum(1 for n in all_nodes if n.get("element_count", 0) > 0)
    empty        = sum(1 for n in all_nodes if n.get("element_count", 0) == 0)

    log.info("Sections: %d total, %d with content, %d empty",
             len(all_nodes), with_content, empty)
    if unassigned:
        log.warning("Unassigned elements: %d", len(unassigned))

    _write_output(output_dir, section_code, profile, section_map, tree, unassigned)
    return True


def _write_output(
    output_dir:   Path,
    section_code: str,
    profile:      dict,
    section_map:  dict,
    tree:         list[dict],
    unassigned:   list,
) -> None:
    """
    Output shape matches the agreed contract exactly.
    Shared profile fields come first, then adapter-specific fields.
    """
    sa = profile.get("structural_authority", {})

    out_doc = {
        # ── Shared profile (identical structure in both adapters) ──────────────
        "schema_version": profile.get("schema_version", "1.0"),
        "schema_type":    profile.get("schema_type", "shared_document_profile"),
        "document_id":    profile.get("document_id"),
        "source_file":    profile.get("source_file"),
        "metadata":       profile.get("metadata", {}),
        "pdf_profile":    profile.get("pdf_profile", {}),
        "vehicle":        profile.get("vehicle", {}),
        "section":        profile.get("section", {}),
        "processing":     profile.get("processing", {}),

        # ── Cars adapter specific ──────────────────────────────────────────────
        "structural_authority": {
            "primary_source":      sa.get("primary_source"),
            "outline_available":   sa.get("outline_available"),
            "outline_entry_count": sa.get("outline_entry_count"),
            "fallback_chain":      sa.get("fallback_chain", []),
        },
        "sections":   tree,
        "unassigned": unassigned,
    }

    out_path = output_dir / f"{section_code}_sectioned.json"
    out_path.write_text(
        json.dumps(out_doc, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("Written: %s", out_path)


if __name__ == "__main__":
    run(raw_dir="raw", output_dir="output")