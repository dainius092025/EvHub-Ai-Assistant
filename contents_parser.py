"""
contents_parser.py — Build precise section map from PDF internal outline
Runs after detector.py, before section_classifier.py.
Writes: raw/section_map.json

Key fix over previous version:
  - Y coordinates extracted from /Top field in outline destination
  - Same-page boundary uses Y position, not just page number
  - Each entry stores both page_pdf + top_y as start anchor
  - End boundary = next sibling's page + top_y (or parent's end)
  - Handles PDF Y coord system: higher Y = higher on page (origin at bottom)
"""

from __future__ import annotations
import json, logging, re, uuid
from pathlib import Path

import fitz
from pypdf import PdfReader

import config

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger("contents_parser")

_PAGE_RE = re.compile(config.NISSAN_PAGE_REF_PATTERN)


# ── Outline extraction ────────────────────────────────────────────────────────

def _extract_outline_flat(r: PdfReader) -> list[dict]:
    """
    Extract all outline entries as a flat ordered list.
    Each entry has: depth, title, page_pdf (1-based), top_y (PDF points).
    PDF Y coord: origin at bottom-left, higher Y = higher on page.
    """
    results: list[dict] = []

    def _walk(items, depth: int = 0) -> None:
        for item in items:
            if isinstance(item, list):
                _walk(item, depth + 1)
                continue
            try:
                page = r.get_destination_page_number(item) + 1
            except Exception:
                page = None

            top_y = None
            try:
                val = item.get("/Top")
                if val is not None:
                    top_y = float(val)
            except Exception:
                pass

            results.append({
                "depth":  depth,
                "title":  (item.title or "").strip(),
                "page":   page,
                "top_y":  top_y,
            })

    _walk(r.outline)
    log.info("Outline: %d raw entries extracted", len(results))
    return results


def _assign_boundaries(flat: list[dict], total_pages: int) -> list[dict]:
    """
    Assign end boundaries to each outline entry.

    For each entry at index i:
      - Its content starts at (page_i, top_y_i)
      - Its content ends just before the NEXT entry at the SAME depth or shallower
      - If no such next entry exists → runs to end of document

    This means a child entry's content ends before its next sibling,
    but a parent's content ends at whatever its last descendant ends at.
    """
    n = len(flat)
    entries = []

    for i, entry in enumerate(flat):
        # Find next entry at same depth or shallower (same level or parent level)
        end_page  = total_pages
        end_top_y = 0.0   # bottom of page = 0 in PDF coords

        for j in range(i + 1, n):
            nxt = flat[j]
            if nxt["depth"] <= entry["depth"]:
                end_page  = nxt["page"] or total_pages
                end_top_y = nxt["top_y"] if nxt["top_y"] is not None else 0.0
                break

        entries.append({
            **entry,
            "end_page":  end_page,
            "end_top_y": end_top_y,
        })

    return entries


def _build_tree(flat: list[dict]) -> list[dict]:
    """
    Convert flat ordered list into nested tree using depth field.
    Returns list of root nodes (depth == min_depth).
    """
    root: list[dict] = []
    stack: list[dict] = []

    for i, entry in enumerate(flat):
        node = {
            "id":              str(uuid.uuid4())[:8],
            "title":           entry["title"],
            "level":           entry["depth"],
            "page_pdf_start":  entry["page"],
            "top_y_start":     entry["top_y"],
            "page_pdf_end":    entry["end_page"],
            "top_y_end":       entry["end_top_y"],
            "manual_page_start": None,
            "manual_page_end":   None,
            "children":        [],
        }

        # Pop stack until we find the right parent
        while stack and stack[-1]["level"] >= entry["depth"]:
            stack.pop()

        if stack:
            stack[-1]["children"].append(node)
        else:
            root.append(node)

        stack.append(node)

    return root


def _count_nodes(nodes: list[dict]) -> int:
    total = 0
    for n in nodes:
        total += 1
        total += _count_nodes(n.get("children", []))
    return total


# ── Manual page stamping ──────────────────────────────────────────────────────

def _build_page_map(pdf_path: Path) -> dict[int, str]:
    """
    Scan PDF footers to build {page_pdf: page_manual} map.
    Uses fitz for speed.
    """
    doc      = fitz.open(str(pdf_path))
    page_map: dict[int, str] = {}
    h_pct    = config.FOOTER_HEIGHT_PCT

    for i in range(doc.page_count):
        page = doc[i]
        h    = page.rect.height
        clip = fitz.Rect(0, h * (1 - h_pct), page.rect.width, h)
        text = page.get_text("text", clip=clip).strip()
        m    = _PAGE_RE.search(text)
        if m:
            page_map[i + 1] = m.group(1)

    total = doc.page_count
    doc.close()
    log.info("Page map: %d / %d pages resolved", len(page_map), total)
    return page_map


def _stamp_manual_pages(nodes: list[dict], page_map: dict[int, str]) -> None:
    for node in nodes:
        s = node.get("page_pdf_start")
        e = node.get("page_pdf_end")
        node["manual_page_start"] = page_map.get(s) if s else None
        node["manual_page_end"]   = page_map.get(e) if e else None
        _stamp_manual_pages(node.get("children", []), page_map)


# ── Visual TOC fallback ───────────────────────────────────────────────────────

def _visual_toc_fallback(pdf_path: Path, total_pages: int) -> list[dict]:
    """
    Fallback for PDFs with no internal outline (Chevrolet-style).
    Parses dot-leader TOC lines from first 5 pages.
    """
    doc = fitz.open(str(pdf_path))
    toc_re = re.compile(r"^(.+?)\s*\.{3,}\s*(\d+)\s*$")
    entries = []
    seen    = set()

    for i in range(min(5, doc.page_count)):
        text = doc[i].get_text("text") or ""
        for line in text.split("\n"):
            line = line.strip()
            m    = toc_re.match(line)
            if m:
                title    = m.group(1).strip()
                page_num = int(m.group(2))
                key      = (title.lower(), page_num)
                if key not in seen and len(title) > 3:
                    seen.add(key)
                    entries.append({
                        "depth":     1,
                        "title":     title,
                        "page":      page_num,
                        "top_y":     742.0,
                        "end_page":  page_num + 10,
                        "end_top_y": 0.0,
                    })

    doc.close()
    log.info("Visual TOC fallback: %d entries", len(entries))
    return entries


# ── Entry point ───────────────────────────────────────────────────────────────

def run(
    pdf_path:   str | Path,
    output_dir: str | Path = "raw",
) -> bool:
    pdf = Path(pdf_path)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    if not pdf.exists():
        log.error("PDF not found: %s", pdf)
        return False

    # Load shared_profile for section code
    profile_path = out / "shared_profile.json"
    profile      = {}
    if profile_path.exists():
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
    section_code = profile.get("section", {}).get("code") or "UNKNOWN"

    r           = PdfReader(str(pdf))
    total_pages = len(r.pages)

    # Build page map for manual page stamping
    page_map = _build_page_map(pdf)

    # Extract outline
    flat_raw = _extract_outline_flat(r)
    source   = "internal_outline"

    if not flat_raw:
        log.info("No outline — trying visual TOC fallback")
        flat_raw = _visual_toc_fallback(pdf, total_pages)
        source   = "visual_toc" if flat_raw else "none"

    if not flat_raw:
        log.warning("No structure found — section map will be empty")
        section_map = {
            "source":         "none",
            "section_code":   section_code,
            "total_sections": 0,
            "sections":       [],
        }
        out_path = out / "section_map.json"
        out_path.write_text(
            json.dumps(section_map, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return True

    # Assign end boundaries using Y coordinates
    flat_with_ends = _assign_boundaries(flat_raw, total_pages)

    # Build nested tree
    tree = _build_tree(flat_with_ends)

    # Stamp manual page references
    _stamp_manual_pages(tree, page_map)

    section_map = {
        "source":         source,
        "section_code":   section_code,
        "total_pages":    total_pages,
        "total_sections": _count_nodes(tree),
        "sections":       tree,
    }

    out_path = out / "section_map.json"
    out_path.write_text(
        json.dumps(section_map, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    log.info(
        "section_map.json written: source=%s total_sections=%d",
        source, section_map["total_sections"],
    )
    return True


if __name__ == "__main__":
    run(pdf_path="PDF/ha.pdf", output_dir="raw")