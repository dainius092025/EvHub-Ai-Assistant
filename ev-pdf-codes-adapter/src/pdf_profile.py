import re
import fitz
from pathlib import Path

# Matches section-code prefixes in PDF page labels (e.g. "EVB-", "TM-", "BRCA-")
_SECTION_PREFIX_RE = re.compile(r'^([A-Z]{2,5})-')


def detect_merged(pdf: fitz.Document) -> dict:
    """
    Analyses structural signals to determine if a PDF is a merged manual
    (multiple workshop sections stitched into one file).
    Call only on digital PDFs — scanned PDFs have no useful page labels or TOC.

    Signals:
      - Page label prefix restarts (EVB- → EVC- → TM-...)  score +3
      - TOC with 5+ top-level sections                      score +2
      - TOC with 2-4 top-level sections                     score +1 (weak)

    Scoring:
      >= 3 → is_merged=True,  confidence="high"
      >= 2 → is_merged=True,  confidence="medium"
      >= 1 → is_merged=False, confidence="low"
         0 → is_merged=False, confidence="high"
    """
    evidence = []
    notes = []
    score = 0

    # ── Signal 1: page label prefix restarts ──────────────────────────────
    # get_page_labels() returns a list of dicts, each defining a labeling range.
    # Multiple distinct section-code prefixes = strong merged signal.
    try:
        page_labels = pdf.get_page_labels()
        seen = {}  # code → first startpage seen (preserves insertion order)
        for entry in page_labels:
            prefix = entry.get("prefix", "")
            m = _SECTION_PREFIX_RE.match(prefix)
            if m:
                code = m.group(1)
                if code not in seen:
                    seen[code] = entry.get("startpage", "?")
        unique_codes = list(seen.keys())
        if len(unique_codes) >= 2:
            score += 3
            evidence.append(
                f"page labels have {len(unique_codes)} distinct section prefixes: "
                + ", ".join(unique_codes)
            )
        elif len(unique_codes) == 1:
            notes.append(f"single section prefix in page labels: {unique_codes[0]}")
        else:
            notes.append("no section-code prefixes found in page labels")
    except Exception as e:
        notes.append(f"could not read page labels: {e}")

    # ── Signal 2: TOC top-level section count ─────────────────────────────
    # get_toc() returns [[level, title, page], ...].
    # Many level-1 entries suggests a multi-section merged document.
    try:
        toc = pdf.get_toc()
        top_level_count = sum(1 for entry in toc if entry[0] == 1)
        if top_level_count >= 5:
            score += 2
            evidence.append(f"TOC has {top_level_count} top-level sections")
        elif top_level_count >= 2:
            score += 1
            notes.append(f"TOC has {top_level_count} top-level sections (weak signal)")
        else:
            notes.append(f"TOC has {top_level_count} top-level section(s) — no signal")
    except Exception as e:
        notes.append(f"could not read TOC: {e}")

    # ── Confidence and verdict ─────────────────────────────────────────────
    if score >= 3:
        is_merged = True
        confidence = "high"
    elif score >= 2:
        is_merged = True
        confidence = "medium"
    elif score >= 1:
        is_merged = False
        confidence = "low"
        notes.append("weak signal — treating as single manual")
    else:
        is_merged = False
        confidence = "high"

    return {
        "is_merged":  is_merged,
        "confidence": confidence,
        "evidence":   evidence,
        "notes":      notes,
    }


def profile_pdf(pdf_path: Path) -> dict:
    """
    Quick pre-check before extraction starts.
    Samples a few pages to decide how to process the PDF.
    Returns two dicts: metadata and pdf_profile.
    """
    pdf = fitz.open(str(pdf_path))

    # ── METADATA ──────────────────────────────────────────────────────────
    # doc.metadata is a dict PyMuPDF reads from the PDF header
    meta = pdf.metadata
    metadata = {
        "title":             meta.get("title")        or None,  # document title
        "author":            meta.get("author")       or None,  # document author
        "subject":           meta.get("subject")      or None,  # subject field (often empty)
        "keywords":          meta.get("keywords")     or None,  # keyword tags (often empty)
        "creator":           meta.get("creator")      or None,  # software that created the PDF
        "producer":          meta.get("producer")     or None,  # software that produced the PDF
        "format":            meta.get("format")       or None,  # PDF version e.g. "PDF 1.4"
        "creation_date":     meta.get("creationDate") or None,
        "modification_date": meta.get("modDate")      or None,
        "encryption":        meta.get("encryption") or None,       # null = not encrypted; string value = encryption type
    }

    # ── DIGITAL DETECTION ─────────────────────────────────────────────────
    # Sample first 5 pages — enough for a quick decision
    sample_pages = min(5, len(pdf))
    pages_with_text = 0

    for i in range(sample_pages):
        page = pdf[i]
        text = page.get_text("text").strip()
        if len(text) > 50:       # more than 50 chars = real text, not noise
            pages_with_text += 1

    # if any sampled page has text, treat as digital
    # a hybrid PDF (mostly digital, few scanned pages) still counts as digital here
    # per-page OCR fallback handles the scanned pages during extraction
    is_digital = pages_with_text > 0

    # classify pdf type - used by pipeline to decide whether to process or skip
    # "digital" - has text layer, full extraction supported
    # "merged"  - detected as multiple manuals combined (see detect_merged below)
    # "scanned" - no text layer, needs OCR
    pdf_type = "digital" if is_digital else "scanned"

    # ── MERGED DETECTION ──────────────────────────────────────────────────
    # Only run on digital PDFs — scanned PDFs have no page labels or useful TOC.
    merged_detection = None
    if is_digital:
        merged_detection = detect_merged(pdf)
        if merged_detection["is_merged"] and merged_detection["confidence"] in ("medium", "high"):
            pdf_type = "merged"

    # ── LINK DETECTION ────────────────────────────────────────────────────
    # Sample first 5 pages for links
    # kind == 4 means internal link (points to another page in the same PDF)
    link_count = 0
    has_internal_links = False

    for i in range(sample_pages):
        page = pdf[i]
        links = page.get_links()
        internal = [l for l in links if l["kind"] == 4]
        link_count += len(internal)
        if internal:
            has_internal_links = True

    pdf_profile = {
        "is_digital":          is_digital,
        "needs_ocr":           not is_digital,
        "has_links":           link_count > 0,
        "has_internal_links":  has_internal_links,
        "link_count_sample":   link_count,
        "pdf_type":            pdf_type,           # "digital", "merged", or "scanned"
        "merged_detection":    merged_detection,   # None for scanned PDFs
    }


    pdf.close()
    return metadata, pdf_profile