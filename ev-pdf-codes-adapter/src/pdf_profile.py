import fitz
from pathlib import Path


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

    #classify pdf type - used by pipeline to decide whether to rpocess or skip
    #"digital" - has txt layer, full eextraction supported
    #"merged" - detected as multiple manuals combined - handled seperately (issue #20)
    pdf_type = "digital" if is_digital else "scanned"

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
        "pdf_type":            pdf_type    # "digital" or "scanned" — drives pipeline decision
    }


    pdf.close()
    return metadata, pdf_profile