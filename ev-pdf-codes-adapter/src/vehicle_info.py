"""
vehicle_info.py
===============
Extracts vehicle make, model, year, variant and revision date from a PDF.

Priority chain:
  year / model / variant / revision_date  →  footer (every page, always present)
  make                                    →  foreword → metadata → lookup → null

The source block records exactly where each piece of information was found.
"""

import re
import json
import fitz
from pathlib import Path

from content_extractor import read_page_ref


# ── Regex patterns ────────────────────────────────────────────────────────────

# "Revision: October 2013"  or  "Revision: 2010 November"
_REVISION_RE = re.compile(r'^Revision:\s*(.+)$', re.IGNORECASE)

# Page refs like "EVB-1", "GI-16" — used to skip those lines in footer
_PAGE_REF_RE = re.compile(r'^[A-Z]{2,5}-\d+$')

# Footer vehicle line: "2013 LEAF", "LEAF", "2015 Leaf NAM"
# Groups: (year_optional, model, variant_optional)
_FOOTER_VEHICLE_RE = re.compile(
    r'^(\d{4})?\s*([A-Za-z][A-Za-z0-9\-\.]*(?:\s+[A-Za-z0-9\-\.]+)?)\s*([A-Z]{2,})?$'
)

# Foreword text: "maintenance and repair procedure for the 2011 NISSAN LEAF"
_FOREWORD_RE = re.compile(
    r'for the (\d{4})\s+([A-Z][A-Z\-]+)\s+([A-Z][A-Z0-9\-]+)',
    re.IGNORECASE
)

_LOOKUP_PATH = Path(__file__).resolve().parents[2] / "shared" / "vehicle_lookup.json"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_lookup() -> dict:
    if not _LOOKUP_PATH.exists():
        return {}
    with open(_LOOKUP_PATH, encoding="utf-8") as f:
        return json.load(f)


def _parse_footer(page: fitz.Page) -> dict:
    """
    Extract revision_date, year, model, variant from the footer area.
    Only looks at the last 3 non-empty lines — the vehicle line and
    revision line always appear at the very bottom of the footer.
    Returns a dict (all values may be None).
    """
    rect = page.rect
    footer_rect = fitz.Rect(0, rect.height * 0.88, rect.width, rect.height)
    raw = page.get_text("text", clip=footer_rect)

    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    tail = lines[-3:]  # last 3 non-empty lines — Revision + vehicle + maybe one more

    result = {"revision_date": None, "year": None, "model": None, "variant": None}

    for line in tail:
        # Skip page refs like "EVB-1"
        if _PAGE_REF_RE.match(line):
            continue

        # Revision line
        m = _REVISION_RE.match(line)
        if m:
            result["revision_date"] = m.group(1).strip()
            continue

        # Vehicle line
        m = _FOOTER_VEHICLE_RE.match(line)
        if m:
            result["year"]  = m.group(1) or None
            model           = m.group(2).strip() if m.group(2) else None
            result["variant"] = m.group(3).strip() if m.group(3) else None

            # "Leaf NAM" → model="Leaf", variant="NAM"
            # If the regex put a trailing all-uppercase word into model, split it off
            if model and " " in model:
                parts = model.rsplit(" ", 1)
                if re.match(r'^[A-Z]{2,4}$', parts[1]):
                    model             = parts[0]
                    result["variant"] = parts[1]

            result["model"] = model

    return result


def _try_foreword(pdf: fitz.Document) -> tuple:
    """
    Scan the first 10 pages for foreword text like:
    "maintenance and repair procedure for the 2011 NISSAN LEAF"

    Returns (info_dict, pdf_page, page_ref) if found.
    Returns (None, None, None) if nothing found.
    """
    for i in range(min(10, len(pdf))):
        page = pdf[i]
        text = page.get_text("text")
        m = _FOREWORD_RE.search(text)
        if m:
            return (
                {
                    "year":  m.group(1),
                    "make":  m.group(2).title(),    # "NISSAN" → "Nissan"
                    "model": m.group(3).upper(),    # normalise to uppercase
                },
                i + 1,              # pdf_page (1-indexed)
                read_page_ref(page),
            )
    return None, None, None


def _try_metadata(metadata: dict) -> dict | None:
    """
    Try to extract year, make, model from the PDF metadata title field.
    e.g. "2013 Nissan LEAF Service Manual"
    Returns a dict or None if nothing useful found.
    """
    title = (metadata or {}).get("title", "") or ""
    if not title:
        return None

    m = re.search(r'(\d{4})\s+([A-Za-z]+)\s+([A-Za-z0-9\-]+)', title)
    if m:
        return {
            "year":  m.group(1),
            "make":  m.group(2),
            "model": m.group(3).upper(),
        }
    return None


# ── Main entry point ──────────────────────────────────────────────────────────

def extract_vehicle_info(pdf_path: Path, metadata: dict) -> dict:
    """
    Returns the vehicle block for the document-level JSON.

    Priority for make:            foreword → metadata → lookup → null
    Priority for year/model:      foreword → footer → null
    revision_date and variant:    footer only
    """
    lookup = _load_lookup()

    result = {
        "year":          None,
        "make":          None,
        "model":         None,
        "variant":       None,
        "revision_date": None,
        "source":        None,
    }

    with fitz.open(str(pdf_path)) as pdf:

        # ── Step 1: Footer — always present, gives revision_date/year/model/variant ──
        footer_info = _parse_footer(pdf[0])
        if footer_info.get("model"):
            result.update(footer_info)
            result["source"] = {
                "method":   "footer",
                "pdf_page": 1,
                "page_ref": read_page_ref(pdf[0]),
            }

        # ── Step 2: Foreword — has make, confirms year + model ──
        foreword_info, fw_page, fw_ref = _try_foreword(pdf)
        if foreword_info:
            result["year"]  = foreword_info.get("year")  or result["year"]
            result["make"]  = foreword_info.get("make")
            result["model"] = foreword_info.get("model") or result["model"]
            result["source"] = {
                "method":   "foreword",
                "pdf_page": fw_page,
                "page_ref": fw_ref,
            }

        # ── Step 3: Metadata — fills make if foreword didn't find it ──
        if not result["make"]:
            meta_info = _try_metadata(metadata)
            if meta_info:
                result["make"]  = meta_info.get("make")
                result["year"]  = meta_info.get("year")  or result["year"]
                result["model"] = meta_info.get("model") or result["model"]
                result["source"] = {
                    "method":   "metadata",
                    "pdf_page": None,
                    "page_ref": None,
                }

        # ── Step 4: Lookup — derives make from model name ──
        if not result["make"] and result["model"]:
            model_key = result["model"].upper()
            make = lookup.get(model_key)
            if make:
                result["make"] = make
                # Source stays as footer/foreword — we know where model came from.
                # Add a flag to show make came from the lookup file.
                if result["source"]:
                    result["source"]["make_from_lookup"] = True
                else:
                    result["source"] = {
                        "method":          "lookup",
                        "pdf_page":        None,
                        "page_ref":        None,
                        "make_from_lookup": True,
                    }

    return result
