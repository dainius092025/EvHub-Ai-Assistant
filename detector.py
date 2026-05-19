"""
detector.py — Stage 1: Document identity and capability profiling
Runs BEFORE extraction. Writes shared_profile.json.

Responsibilities (only these):
  - PDF metadata extraction
  - Footer/header page reference detection
  - Manufacturer/model/year/section identity resolution
  - PDF outline (bookmarks) discovery
  - OCR need detection
  - Writing shared_profile.json

Does NOT:
  - Extract content
  - Filter noise
  - Make semantic decisions
  - Touch raw batch files
"""

from __future__ import annotations
import hashlib, json, logging, re
from datetime import datetime, timezone
from pathlib import Path

import fitz

import config

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger("detector")

_PAGE_RE      = re.compile(config.NISSAN_PAGE_REF_PATTERN)
_YEAR_RE      = re.compile(config.YEAR_PATTERN)
_MODEL_YEAR_RE = re.compile(
    r"\b(20\d{2}|19\d{2})\s+(?:" + "|".join(config.NISSAN_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _document_id(pdf: Path) -> str:
    """SHA-256 of PDF file bytes. Stable across runs. Matches DTC adapter."""
    return hashlib.sha256(pdf.read_bytes()).hexdigest()


def _read_region(doc: fitz.Document, page_no: int,
                 y_start_pct: float, y_end_pct: float) -> str:
    if page_no >= doc.page_count:
        return ""
    page   = doc[page_no]
    h      = page.rect.height
    region = fitz.Rect(0, h * y_start_pct, page.rect.width, h * y_end_pct)
    return page.get_text("text", clip=region).strip()


def _read_full(doc: fitz.Document, page_no: int) -> str:
    if page_no >= doc.page_count:
        return ""
    return doc[page_no].get_text("text") or ""


# ── Detection strategies ──────────────────────────────────────────────────────

def _detect_metadata(doc: fitz.Document) -> dict:
    meta = doc.metadata or {}
    return {
        "title":             meta.get("title"),
        "author":            meta.get("author"),
        "subject":           meta.get("subject"),
        "keywords":          meta.get("keywords"),
        "creator":           meta.get("creator"),
        "producer":          meta.get("producer"),
        "format":            meta.get("format"),
        "creation_date":     meta.get("creationDate"),
        "modification_date": meta.get("modDate"),
        "encryption":        meta.get("encryption"),
    }


def _detect_footer(doc: fitz.Document) -> dict:
    """
    Scan first 10 pages footer then header for Nissan page reference.
    Returns section_code, year, model_keyword, raw text, confidence.
    All Nissan-specific patterns come from config.
    """
    result = {
        "section_code":      None,
        "year":              None,
        "model_keyword":     None,
        "footer_text":       None,
        "page_ref_pattern":  None,
        "page_ref_location": None,
        "confidence":        0.0,
    }

    for i in range(min(10, doc.page_count)):
        for region_text, location in [
            (_read_region(doc, i, 1 - config.FOOTER_HEIGHT_PCT, 1.0), "footer"),
            (_read_region(doc, i, 0.0, config.HEADER_HEIGHT_PCT), "header"),
        ]:
            if not region_text:
                continue

            match = _PAGE_RE.search(region_text)
            if not match:
                continue

            page_ref = match.group(1)                 # e.g. "VC-1"
            code     = page_ref.split("-")[0]         # e.g. "VC"
            result["section_code"]      = code
            result["page_ref"]          = page_ref
            result["footer_text"]       = region_text
            result["page_ref_pattern"]  = config.NISSAN_PAGE_REF_PATTERN
            result["page_ref_location"] = location
            result["confidence"]        = 0.97

            # Prefer year immediately before a model keyword (model year "2015 LEAF")
            # over bare year (revision year "June 2014")
            model_year = _MODEL_YEAR_RE.search(region_text.upper())
            if model_year:
                result["year"] = model_year.group(1)
            else:
                year_match = _YEAR_RE.search(region_text)
                if year_match:
                    result["year"] = year_match.group(1)

            upper = region_text.upper()
            for kw in config.NISSAN_KEYWORDS:
                if kw in upper:
                    result["model_keyword"] = kw
                    break

            log.info("  Footer: section=%s year=%s model=%s (page %d via %s)",
                     code, result["year"], result["model_keyword"], i + 1, location)
            return result

    log.warning("  Footer: no page reference found in first 10 pages")
    return result


def _resolve_manufacturer(model_keyword: str | None) -> dict:
    """
    Map model keyword to make, model name, is_ev.
    Uses config.NISSAN_EV_MODELS for EV determination.
    """
    if not model_keyword:
        return {"make": None, "model": None, "is_ev": None}

    upper = model_keyword.upper()
    # Nissan only for now — extend in Phase 3
    if any(kw in upper or upper in kw for kw in config.NISSAN_KEYWORDS):
        is_ev = any(ev in upper or upper in ev for ev in config.NISSAN_EV_MODELS)
        model = next(
            (ev.title() for ev in config.NISSAN_EV_MODELS if ev in upper),
            model_keyword.title(),
        )
        return {"make": "Nissan", "model": model, "is_ev": is_ev}

    return {"make": None, "model": model_keyword.title(), "is_ev": None}


def _detect_outline(doc: fitz.Document) -> dict:
    """
    Extract PDF internal outline (bookmarks).
    Determines structural authority primary source.
    """
    result = {
        "outline_available":   False,
        "outline_entry_count": 0,
        "primary_source":      config.STRUCTURAL_AUTHORITY_PRIORITY[-1],
        "fallback_chain":      config.STRUCTURAL_AUTHORITY_PRIORITY[1:],
    }

    try:
        toc = doc.get_toc(simple=False)
        if toc:
            result["outline_available"]   = True
            result["outline_entry_count"] = len(toc)
            result["primary_source"]      = config.STRUCTURAL_AUTHORITY_PRIORITY[0]
            result["fallback_chain"]      = config.STRUCTURAL_AUTHORITY_PRIORITY[1:]
            log.info("  Outline: %d entries → primary_source=internal_outline", len(toc))
        else:
            result["primary_source"] = "footer_pattern"
            log.info("  Outline: none → primary_source=footer_pattern")
    except Exception as exc:
        log.warning("  Outline extraction failed: %s", exc)

    return result


def _detect_capabilities(doc: fitz.Document) -> dict:
    """
    Detect OCR need and link presence.
    Scans first 5 pages. OCR threshold comes from config.
    """
    scan_pages  = min(5, doc.page_count)
    total_chars = 0
    total_links = 0
    has_internal = False

    for i in range(scan_pages):
        page         = doc[i]
        total_chars += len(page.get_text("text") or "")
        links        = page.get_links()
        total_links += len(links)
        if any(lk.get("kind") == fitz.LINK_GOTO for lk in links):
            has_internal = True

    avg = total_chars / scan_pages if scan_pages else 0
    needs_ocr = avg < config.OCR_THRESHOLD_CHARS

    if needs_ocr:
        log.info("  OCR: avg %.0f chars/page → scanned", avg)
    else:
        log.info("  OCR: avg %.0f chars/page → digital", avg)

    return {
        "is_digital":         not needs_ocr,
        "needs_ocr":          needs_ocr,
        "has_links":          total_links > 0,
        "has_internal_links": has_internal,
        "pdf_type":           "scanned" if needs_ocr else "digital",
        "link_count_sample":  total_links,
    }


# ── Profile assembly ──────────────────────────────────────────────────────────

def _load_existing(out: Path) -> dict:
    path = out / "shared_profile.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "schema_version": "1.0",
        "schema_type":    "shared_document_profile",
        "document_id":    None,
        "source_file":    None,
        "metadata":           {},
        "pdf_profile":        {},
        "vehicle":            {"source": {}},
        "section":            {},
        "structural_authority": {},
        "processing": {
            "adapter_name":         "ev-pdf-cars-adapter",
            "extraction_status":    "pending",
            "extraction_completed": False,
            "extracted_at":         None,
            "errors":               [],
        },
    }


def _fill(target: dict, key: str, value) -> None:
    """Set key only if currently None or missing."""
    if target.get(key) is None:
        target[key] = value


def _build_profile(pdf: Path, doc: fitz.Document, existing: dict) -> dict:
    log.info("Detection: %s", pdf.name)

    meta_det     = _detect_metadata(doc)
    footer_det   = _detect_footer(doc)
    outline_det  = _detect_outline(doc)
    caps_det     = _detect_capabilities(doc)

    mfr    = _resolve_manufacturer(footer_det["model_keyword"])
    year   = footer_det["year"]
    sec_cd = footer_det["section_code"]
    sec_nm = config.NISSAN_SECTION_NAMES.get(sec_cd) if sec_cd else None

    p = existing

    _fill(p, "document_id", _document_id(pdf))
    _fill(p, "source_file", pdf.name)

    md = p.setdefault("metadata", {})
    for k, v in meta_det.items():
        _fill(md, k, v)

    pp = p.setdefault("pdf_profile", {})
    for k, v in caps_det.items():
        _fill(pp, k, v)

    vh = p.setdefault("vehicle", {})
    _fill(vh, "year",  year)
    _fill(vh, "make",  mfr["make"])
    _fill(vh, "model", mfr["model"])
    _fill(vh, "is_ev", mfr["is_ev"])

    src = vh.setdefault("source", {})
    if src.get("method") is None and footer_det["footer_text"]:
        src.update({
            "method":           footer_det["page_ref_location"] or "footer",
            "pdf_page":         1,
            "page_ref":         footer_det.get("page_ref") or footer_det["section_code"],
            "make_from_lookup": True,
            "confidence":       footer_det["confidence"],
        })

    sec = p.setdefault("section", {})
    _fill(sec, "code",             sec_cd)
    _fill(sec, "name",             sec_nm)
    _fill(sec, "manual_type",      "workshop")
    _fill(sec, "page_count",       doc.page_count)
    _fill(sec, "page_ref_pattern", footer_det["page_ref_pattern"])
    _fill(sec, "page_ref_location", footer_det["page_ref_location"])

    sa = p.setdefault("structural_authority", {})
    _fill(sa, "primary_source",      outline_det["primary_source"])
    _fill(sa, "outline_available",   outline_det["outline_available"])
    _fill(sa, "outline_entry_count", outline_det["outline_entry_count"])
    _fill(sa, "fallback_chain",      outline_det["fallback_chain"])

    proc = p.setdefault("processing", {})
    _fill(proc, "adapter_name",         "ev-pdf-cars-adapter")
    _fill(proc, "extraction_status",    "pending")
    _fill(proc, "extraction_completed", False)
    _fill(proc, "extracted_at",         None)
    if "errors" not in proc:
        proc["errors"] = []

    log.info(
        "Detection complete: make=%s model=%s year=%s section=%s ev=%s outline=%s",
        vh.get("make"), vh.get("model"), vh.get("year"),
        sec.get("code"), vh.get("is_ev"), sa.get("outline_available"),
    )
    return p


# ── Entry point ───────────────────────────────────────────────────────────────

def run(pdf_path: str | Path, output_dir: str | Path = "raw") -> bool:
    pdf = Path(pdf_path)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    if not pdf.exists():
        log.error("PDF not found: %s", pdf)
        return False

    doc      = fitz.open(str(pdf))
    existing = _load_existing(out)

    try:
        profile = _build_profile(pdf, doc, existing)
    except Exception:
        log.exception("Detection failed")
        doc.close()
        return False
    finally:
        doc.close()

    path = out / "shared_profile.json"
    path.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("shared_profile.json → %s", path)
    return True


if __name__ == "__main__":
    run(pdf_path="PDF/ha.pdf", output_dir="raw")