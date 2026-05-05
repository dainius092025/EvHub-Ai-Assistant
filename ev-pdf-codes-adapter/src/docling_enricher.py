"""
docling_enricher.py
===================
Post-processor: enrich pipeline output JSON with Docling table extraction.

For each DTC record, Docling is run on the record's pages and the extracted
tables are added as a tables[] field with markdown content.

Key optimisations vs the visual_split_probe:
  - One DocumentConverter instance shared across all pages (model loads once).
  - OCR disabled — text PDFs don't need it, saves significant time.
  - Only DTC pages are processed, not the full PDF.

Reads:   data/<stem>/<stem>.json     pipeline output
         manuals/<stem>.pdf           original PDF
Writes:  data/<stem>/<stem>.json     enriched in-place (atomic write)

Usage:
    python experiments/docling_enricher.py EVB
    python experiments/docling_enricher.py EVB --force
"""

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import fitz  # PyMuPDF


# ── Optional Docling ──────────────────────────────────────────────────────────
DOCLING_AVAILABLE = False
try:
    from docling.document_converter import DocumentConverter
    DOCLING_AVAILABLE = True
except ImportError:
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Converter setup
# ─────────────────────────────────────────────────────────────────────────────

def _build_converter():
    """
    Build a DocumentConverter with OCR disabled.
    Falls back to default settings if the pipeline options API is not available
    in the installed version of Docling.
    """
    try:
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import PdfFormatOption
        from docling.datamodel.base_models import InputFormat

        opts = PdfPipelineOptions()
        opts.do_ocr            = False   # PDF has a text layer — OCR not needed
        opts.do_table_structure = True   # this is what we're here for

        return DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
        )
    except Exception as e:
        print(f"  [WARN] Could not set pipeline options ({e!s:.120}); using Docling defaults.")
        return DocumentConverter()


# ─────────────────────────────────────────────────────────────────────────────
# Per-page extraction
# ─────────────────────────────────────────────────────────────────────────────

def _extract_page_tables(converter, pdf_path: Path, page_num: int) -> list:
    """
    Run Docling on a single page and return a list of table dicts.

    Each dict:
        {
            "pdf_page": int,
            "source":   "docling",
            "markdown": str,   # Docling markdown table
        }

    Returns [] on any failure — the caller always continues.
    """
    tmp_path = None
    try:
        # Extract the target page into a fresh single-page temp PDF.
        # Docling crashes on large files (memory) so we always give it one page.
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            tmp_path = Path(f.name)

        src     = fitz.open(str(pdf_path))
        tmp_doc = fitz.open()
        tmp_doc.insert_pdf(src, from_page=page_num - 1, to_page=page_num - 1)
        tmp_doc.save(str(tmp_path))
        tmp_doc.close()
        src.close()

        result = converter.convert(str(tmp_path))

        tables = []
        for t in result.document.tables:
            # export_to_dict() was removed in newer Docling versions.
            # export_to_markdown() requires doc= argument to avoid deprecation warning.
            if hasattr(t, "export_to_markdown"):
                md = t.export_to_markdown(doc=result.document)
            elif hasattr(t, "model_dump"):
                md = str(t.model_dump())
            else:
                md = str(t)

            tables.append({
                "pdf_page": page_num,
                "source":   "docling",
                "markdown": md,
            })

        return tables

    except Exception as e:
        print(f"    [WARN] Docling failed on page {page_num}: {e!s:.200}")
        return []

    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink()


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Enrich pipeline JSON with Docling table extraction."
    )
    parser.add_argument(
        "stem",
        help="PDF stem to enrich (e.g. EVB). Reads data/<stem>/<stem>.json.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-enrich even if already done.",
    )
    args = parser.parse_args()
    stem = args.stem

    # ── Check Docling ─────────────────────────────────────────────────────────
    if not DOCLING_AVAILABLE:
        print("Docling is not installed.  Run:  pip install docling")
        sys.exit(1)

    # ── Load pipeline output ──────────────────────────────────────────────────
    json_path = Path("data") / stem / f"{stem}.json"
    if not json_path.exists():
        print(f"Pipeline output not found: {json_path}")
        print("Run the main pipeline first:  python src/pipeline.py")
        sys.exit(1)

    data    = json.loads(json_path.read_text(encoding="utf-8"))
    records = data.get("records", [])
    if not records:
        print("No DTC records found in pipeline output — nothing to enrich.")
        sys.exit(0)

    # ── Skip if already enriched ──────────────────────────────────────────────
    processing = data.get("processing", {})
    if processing.get("docling_enriched") and not args.force:
        enriched_at = processing.get("docling_enriched_at", "unknown time")
        print(f"Already enriched ({enriched_at}).  Use --force to re-enrich.")
        sys.exit(0)

    # ── Locate PDF ────────────────────────────────────────────────────────────
    pdf_path = Path("manuals") / f"{stem}.pdf"
    if not pdf_path.exists():
        print(f"PDF not found: {pdf_path}")
        sys.exit(1)

    # ── Collect unique DTC pages ──────────────────────────────────────────────
    pages_set: set[int] = set()
    for rec in records:
        loc   = rec.get("location", {})
        start = loc.get("start_pdf_page")
        end   = loc.get("end_pdf_page")
        if start and end:
            pages_set.update(range(start, end + 1))

    if not pages_set:
        print("No page ranges found in records — cannot determine which pages to process.")
        sys.exit(1)

    pages = sorted(pages_set)
    print(f"Records  : {len(records)}")
    print(f"DTC pages: {len(pages)}")
    print()
    print("Building Docling converter (model load — one-time cost) ...")

    # ── Build converter ONCE ──────────────────────────────────────────────────
    converter = _build_converter()
    print("Converter ready.\n")

    # ── Process each page ─────────────────────────────────────────────────────
    page_tables: dict[int, list] = {}   # pdf_page -> [table dicts]
    total_found = 0

    for i, page_num in enumerate(pages, 1):
        print(f"  [{i:3}/{len(pages)}] page {page_num:4} ...", end=" ", flush=True)
        tables = _extract_page_tables(converter, pdf_path, page_num)
        page_tables[page_num] = tables
        total_found += len(tables)
        print(f"tables={len(tables)}")

    # ── Attach tables to each record ──────────────────────────────────────────
    total_attached = 0
    for rec in records:
        loc   = rec.get("location", {})
        start = loc.get("start_pdf_page")
        end   = loc.get("end_pdf_page")

        if not start or not end:
            rec["tables"] = []
            continue

        rec_tables = []
        for page_num in range(start, end + 1):
            rec_tables.extend(page_tables.get(page_num, []))

        rec["tables"]   = rec_tables
        total_attached += len(rec_tables)

    # ── Update processing metadata ────────────────────────────────────────────
    if "processing" not in data:
        data["processing"] = {}
    data["processing"]["docling_enriched"]    = True
    data["processing"]["docling_enriched_at"] = datetime.now(timezone.utc).isoformat()

    # ── Atomic write ──────────────────────────────────────────────────────────
    tmp_out = json_path.with_suffix(".json.tmp")
    tmp_out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_out.replace(json_path)

    print()
    print(f"Done.")
    print(f"  Records enriched : {len(records)}")
    print(f"  Tables found     : {total_found}")
    print(f"  Tables attached  : {total_attached}")
    print(f"  Output           : {json_path}")


if __name__ == "__main__":
    main()
