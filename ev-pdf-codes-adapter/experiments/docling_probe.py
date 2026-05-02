"""
docling_probe.py
================
Isolated experiment — DO NOT integrate into the main pipeline.

EXPERIMENT RESULT (2026-04-30):
  Tested on manuals/EVB.pdf. Docling triggered RapidOCR automatically,
  downloaded OCR models, ran on CPU, caused std::bad_alloc crashes on
  multiple pages, and could not complete. Run was killed manually.
  Decision: keep PyMuPDF as main extractor. Docling remains experimental only.
  Future: may be revisited for selected pages or difficult tables only.

Goal: evaluate whether Docling improves layout, heading, table, and text
extraction for EV workshop manuals compared to the current PyMuPDF extractor.

Usage:
    # Safe first test — pages 88–92, no OCR, no table ML
    python experiments/docling_probe.py "manuals/EVB.pdf" --pages 88-92

    # Same range but with table structure recognition enabled
    python experiments/docling_probe.py "manuals/EVB.pdf" --pages 88-92 --tables

    # Full PDF (slow)
    python experiments/docling_probe.py "manuals/EVB.pdf"

Options:
    --pages N-M   Page range to process, e.g. --pages 88-92  [required unless --all-pages]
    --all-pages   Process the full PDF (slow — prints a warning first)
    --start N     Alternative to --pages: first page only (default: 1)
    --end N       Alternative to --pages: last page only (default: last page)
    --ocr         Enable OCR (default: OFF — caused std::bad_alloc crashes)
    --tables      Enable TableFormer table structure ML (default: OFF)

Output files written to experiments/output/docling_probe/<pdf_stem>/:
    docling_document.raw.json   — raw Docling export, never modified
    docling_document.raw.md     — raw Docling markdown, never modified
    docling_document.cleaned.md — noise-filtered markdown (sidebar letters,
                                  section markers, repeated headers removed)
    summary.json                — stats: page count, titles, tables, images

This script does NOT touch any pipeline files, schema, or existing JSON outputs.
"""

import re
import sys
import json
import argparse
from pathlib import Path


# ---------------------------------------------------------------------------
# Step 0 — guard: fail gracefully if Docling is not installed
# ---------------------------------------------------------------------------
try:
    from docling.document_converter import DocumentConverter
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.document import DoclingDocument
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import PdfFormatOption
except ImportError:
    print("Docling is not installed.")
    print("Install it first, then rerun this experiment.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Noise patterns — things we want to strip in the cleaned output only.
# Raw output is never touched.
# ---------------------------------------------------------------------------

# Sidebar navigation letters that appear alone on a line (A–P, excluding C)
# These are section-tab markers printed in the manual margin.
_SIDEBAR_LETTERS = re.compile(r"^[A-P]$")

# Standalone section code marker, e.g. a line containing only "EVB"
_SECTION_MARKER = re.compile(r"^[A-Z]{2,4}$")

# INFOID lines — standalone metadata lines like "INFOID:0000000012345678"
_INFOID_LINE = re.compile(r"^INFOID:\S+$", re.IGNORECASE)

# Repeated footer/header patterns common in Nissan workshop manuals
_FOOTER_PATTERNS = [
    re.compile(r"^Revision:\s*\S.*$", re.IGNORECASE),
    re.compile(r"^\d{4}\s+NISSAN.*$", re.IGNORECASE),       # "2011 NISSAN LEAF ..."
    re.compile(r"^[A-Z]{2,4}-\d+$"),                         # page refs like "EVB-88"
]


def _is_noise_line(line: str) -> bool:
    """Return True if this line is standalone noise that should be removed."""
    s = line.strip()
    if not s:
        return False  # blank lines are handled separately, not noise
    if _SIDEBAR_LETTERS.match(s):
        return True
    if _SECTION_MARKER.match(s):
        return True
    if _INFOID_LINE.match(s):
        return True
    for pat in _FOOTER_PATTERNS:
        if pat.match(s):
            return True
    return False


def _clean_markdown(raw_md: str) -> str:
    """
    Remove known noise lines from a Docling markdown export.

    Rules:
    - Drop lines that match _is_noise_line().
    - Collapse three or more consecutive blank lines into two.
    - Preserve everything else exactly — no rewriting, no reformatting.
    """
    cleaned_lines = []
    blank_run = 0

    for line in raw_md.splitlines():
        if _is_noise_line(line):
            continue  # drop noise line entirely
        if line.strip() == "":
            blank_run += 1
            if blank_run <= 2:           # allow at most two consecutive blanks
                cleaned_lines.append(line)
        else:
            blank_run = 0
            cleaned_lines.append(line)

    return "\n".join(cleaned_lines)


# ---------------------------------------------------------------------------
# Step 1 — parse CLI arguments
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser(description="Docling probe experiment")
parser.add_argument("pdf", help="Path to the PDF file to process")
parser.add_argument(
    "--pages", type=str, default=None,
    help="Page range as N-M, e.g. --pages 88-92 (overrides --start/--end)"
)
parser.add_argument(
    "--start", type=int, default=1,
    help="First page to process, 1-based (default: 1)"
)
parser.add_argument(
    "--end", type=int, default=None,
    help="Last page to process, 1-based inclusive (default: last page of PDF)"
)
parser.add_argument(
    "--ocr", action="store_true", default=False,
    help="Enable OCR (default: OFF — caused std::bad_alloc crashes on large PDFs)"
)
parser.add_argument(
    "--tables", action="store_true", default=False,
    help="Enable Docling TableFormer table structure ML model (default: OFF)"
)
parser.add_argument(
    "--all-pages", action="store_true", default=False,
    help="Process the full PDF (slow and resource-heavy — use for full-PDF evaluation only)"
)
args = parser.parse_args()

# --pages N-M overrides --start / --end when provided
if args.pages is not None:
    match = re.match(r"^(\d+)-(\d+)$", args.pages.strip())
    if not match:
        print(f"Invalid --pages format: '{args.pages}'. Expected N-M, e.g. --pages 88-92")
        sys.exit(1)
    args.start = int(match.group(1))
    args.end   = int(match.group(2))

# Enforce: must supply --pages or --all-pages — never run full PDF silently
if not args.all_pages and args.pages is None and args.start == 1 and args.end is None:
    print("ERROR: you must specify a page range or --all-pages.")
    print("  Controlled test : python experiments/docling_probe.py \"manuals/EVB.pdf\" --pages 88-92")
    print("  Full PDF (slow) : python experiments/docling_probe.py \"manuals/EVB.pdf\" --all-pages")
    sys.exit(1)

pdf_path = Path(args.pdf).resolve()

if not pdf_path.exists():
    print(f"File not found: {pdf_path}")
    sys.exit(1)

if pdf_path.suffix.lower() != ".pdf":
    print(f"Expected a .pdf file, got: {pdf_path.suffix}")
    sys.exit(1)

# Full-PDF mode: warn clearly before starting, use a separate output folder
if args.all_pages:
    print()
    print("WARNING: --all-pages selected.")
    print("  This will process the entire PDF with Docling.")
    print("  Large manuals (200+ pages) may use significant RAM and CPU.")
    print("  OCR is still OFF by default — use --ocr only if needed.")
    print("  Press Ctrl+C now to cancel, or wait 5 seconds to continue ...")
    print()
    import time
    time.sleep(5)

page_end_label = args.end if args.end is not None else "last"
print(f"[probe] input  : {pdf_path}")
if args.all_pages:
    print(f"[probe] pages  : ALL")
else:
    print(f"[probe] pages  : {args.start} – {page_end_label}")
print(f"[probe] OCR    : {'ON' if args.ocr else 'OFF (use --ocr to enable)'}")
print(f"[probe] tables : {'ON (TableFormer ML)' if args.tables else 'OFF (use --tables to enable)'}")

# ---------------------------------------------------------------------------
# Step 2 — set up output directory for this PDF
# ---------------------------------------------------------------------------
# Full-PDF runs go into a separate folder so they never overwrite page-range runs.
# experiments/output/docling_probe/<pdf_stem>/        ← page range runs
# experiments/output/docling_probe/<pdf_stem>_full/   ← --all-pages runs
folder_suffix = "_full" if args.all_pages else ""
output_dir = Path(__file__).parent / "output" / "docling_probe" / (pdf_path.stem + folder_suffix)
output_dir.mkdir(parents=True, exist_ok=True)
print(f"[probe] output : {output_dir}")

# ---------------------------------------------------------------------------
# Step 3 — configure and run Docling
# ---------------------------------------------------------------------------
# OCR off by default — caused RapidOCR crashes on first run.
# TableFormer off by default — runs ML inference, adds memory pressure.
pipeline_options = PdfPipelineOptions()
pipeline_options.do_ocr             = args.ocr
pipeline_options.do_table_structure = args.tables

converter = DocumentConverter(
    format_options={
        InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
    }
)

# IMPORTANT: max_num_pages is NOT "process first N pages" — it is a hard
# document filter that rejects PDFs with more pages than N entirely.
# Use page_range=(start, end) to select a specific range of pages.
convert_kwargs: dict = {"source": str(pdf_path)}
if not args.all_pages:
    # Restrict to the requested page range — do not pass page_range for full-PDF mode
    end = args.end if args.end is not None else 2**62  # effectively "last page"
    convert_kwargs["page_range"] = (args.start, end)   # 1-based inclusive

print("[probe] running Docling ...")
result = converter.convert(**convert_kwargs)
doc: DoclingDocument = result.document
print("[probe] conversion complete")

# ---------------------------------------------------------------------------
# Step 4 — save raw JSON (never modified — source of truth)
# ---------------------------------------------------------------------------
raw_json_path = output_dir / "docling_document.raw.json"
doc_dict = doc.export_to_dict()
raw_json_path.write_text(json.dumps(doc_dict, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"[probe] saved {raw_json_path.name}")

# ---------------------------------------------------------------------------
# Step 5 — save raw Markdown (never modified — source of truth)
# ---------------------------------------------------------------------------
raw_md_path = output_dir / "docling_document.raw.md"
raw_md_text = doc.export_to_markdown()
raw_md_path.write_text(raw_md_text, encoding="utf-8")
print(f"[probe] saved {raw_md_path.name}")

# ---------------------------------------------------------------------------
# Step 6 — save cleaned Markdown (noise removed, raw is unchanged)
# ---------------------------------------------------------------------------
cleaned_md_text = _clean_markdown(raw_md_text)
cleaned_md_path = output_dir / "docling_document.cleaned.md"
cleaned_md_path.write_text(cleaned_md_text, encoding="utf-8")
print(f"[probe] saved {cleaned_md_path.name}")

# ---------------------------------------------------------------------------
# Step 7 — collect stats for summary.json
# ---------------------------------------------------------------------------
titles  = []
tables  = []
images  = []
notes   = []

for item, _level in doc.iterate_items():
    label = getattr(item, "label", None)
    if label is None:
        continue

    label_str = str(label).lower()

    # Headings and section titles
    if label_str in ("title", "section_header"):
        text = getattr(item, "text", "") or ""
        if text.strip() and not _is_noise_line(text.strip()):
            titles.append(text.strip())

    # Tables — report real row/col counts when TableFormer was enabled
    elif label_str == "table":
        table_data = getattr(item, "data", None)
        if table_data is not None:
            try:
                tables.append({"rows": table_data.num_rows, "cols": table_data.num_cols})
            except AttributeError:
                tables.append({"rows": None, "cols": None})
        else:
            # TableFormer was OFF — Docling detected a table region but did not
            # analyse its structure. rows/cols are unknown.
            tables.append({"rows": "unknown", "cols": "unknown",
                           "note": "enable --tables for row/col counts"})

    # Figures and pictures
    elif label_str in ("picture", "figure"):
        images.append(True)

# Page count from the pages dict
page_count = len(doc.pages) if doc.pages else None

# Build notes for summary
if not titles:
    notes.append("no titles or section headers detected by Docling")
if not tables:
    notes.append("no tables detected by Docling")
if not args.ocr:
    notes.append("OCR disabled — text inside raster images/diagrams is not extracted")
if not args.tables:
    notes.append("TableFormer disabled — table row/col counts unknown (use --tables)")
if args.tables and tables:
    # Check if TableFormer ran but still produced only 1x1 tables — this means
    # Docling detected a table region but could not parse its internal structure.
    flat = [t for t in tables if t.get("rows") == 1 and t.get("cols") == 1]
    if len(flat) == len(tables):
        notes.append(
            "WARNING: all tables are 1×1 even with --tables ON — "
            "TableFormer could not parse table structure (common for image-based or "
            "borderless tables in this PDF)"
        )
    elif flat:
        notes.append(
            f"{len(flat)} of {len(tables)} tables are 1×1 — "
            "partial structure failure (those tables may be image-based or borderless)"
        )
if args.start != 1 or args.end is not None:
    notes.append(f"partial run — pages {args.start}–{args.end if args.end else 'last'}")

# ---------------------------------------------------------------------------
# Step 8 — save summary.json
# ---------------------------------------------------------------------------
summary = {
    "source_file":             str(pdf_path),
    "pages_requested":         "all" if args.all_pages else f"{args.start}–{args.end if args.end else 'last'}",
    "page_count":              page_count,
    "ocr_enabled":             args.ocr,
    "table_structure_enabled": args.tables,
    "detected_titles_count":   len(titles),
    "detected_tables_count":   len(tables),
    "detected_images_count":   len(images),
    "sample_titles":           titles[:10],
    "sample_tables":           tables[:5],   # real row/col counts if --tables was used
    "notes":                   notes,
}

summary_path = output_dir / "summary.json"
summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"[probe] saved {summary_path.name}")

# ---------------------------------------------------------------------------
# Step 9 — print human-readable summary to stdout
# ---------------------------------------------------------------------------
print()
print("=" * 60)
print("DOCLING PROBE SUMMARY")
print("=" * 60)
print(f"  pages   : {page_count}")
print(f"  titles  : {len(titles)}")
print(f"  tables  : {len(tables)}")
print(f"  images  : {len(images)}")
print(f"  OCR     : {'ON' if args.ocr else 'OFF'}")
print(f"  tables  : {'ON (TableFormer)' if args.tables else 'OFF'}")
if tables:
    for i, t in enumerate(tables[:3], 1):
        print(f"    table {i}: {t['rows']} rows × {t['cols']} cols")
if notes:
    for note in notes:
        print(f"  NOTE    : {note}")
print()
print(f"Output files:")
print(f"  {raw_json_path.name}   — raw Docling JSON")
print(f"  {raw_md_path.name}    — raw Docling markdown")
print(f"  {cleaned_md_path.name} — cleaned markdown (noise removed)")
print(f"  {summary_path.name}         — stats summary")
print()
print(f"Full output saved to: {output_dir}")
