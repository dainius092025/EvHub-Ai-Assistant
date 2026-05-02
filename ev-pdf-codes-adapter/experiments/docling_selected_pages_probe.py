"""
docling_selected_pages_probe.py
================================
Isolated experiment — DO NOT integrate into the main pipeline.

Goal:
  Test whether Docling improves extraction quality on SELECTED pages only,
  instead of processing the whole PDF. This is the step before deciding
  whether Docling should be used as a fallback, table enhancer, or
  selected-page enhancer in the main pipeline.

Strategy:
  PyMuPDF identifies candidate pages (DTC blocks, tables, weak sections).
  This script accepts those page numbers and runs Docling only on them.
  PyMuPDF output for the same pages is produced in parallel for comparison.

Usage:
    # Single range
    python experiments/docling_selected_pages_probe.py "manuals/EVB.pdf" --pages 88-92

    # Multiple ranges and individual pages
    python experiments/docling_selected_pages_probe.py "manuals/EVB.pdf" --pages 88-92,95,100-103

    # With table structure recognition
    python experiments/docling_selected_pages_probe.py "manuals/EVB.pdf" --pages 88-92 --tables

Options:
    --pages  N,N-M,...  Comma-separated pages or ranges (required)
    --tables            Enable Docling TableFormer ML (default: OFF)
    --ocr               Enable OCR (default: OFF — caused crashes previously)

Output written to:
    experiments/output/docling_selected_pages/<pdf_stem>/
        docling_output.md        — Docling markdown for selected pages
        docling_output.json      — Docling document dict for selected pages
        pymupdf_output.md        — PyMuPDF plain text for same pages (comparison)
        summary.json             — counts, runtime, and comparison notes

This script does NOT touch any pipeline files, schema, or existing JSON outputs.
"""

import re
import sys
import json
import time
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
    print("Install it with: pip install docling")
    sys.exit(1)

try:
    import fitz  # PyMuPDF
except ImportError:
    print("PyMuPDF is not installed.")
    print("Install it with: pip install pymupdf")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Page range parsing
# ---------------------------------------------------------------------------

def parse_page_spec(spec: str) -> list[int]:
    """
    Parse a comma-separated list of pages and ranges into a sorted list of
    unique 1-based page numbers.

    Examples:
        "88-92"         → [88, 89, 90, 91, 92]
        "95"            → [95]
        "88-92,95,100"  → [88, 89, 90, 91, 92, 95, 100]
    """
    pages = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        range_match = re.match(r"^(\d+)-(\d+)$", part)
        single_match = re.match(r"^(\d+)$", part)
        if range_match:
            start, end = int(range_match.group(1)), int(range_match.group(2))
            if start > end:
                print(f"Invalid range '{part}': start must be <= end")
                sys.exit(1)
            pages.update(range(start, end + 1))
        elif single_match:
            pages.add(int(single_match.group(1)))
        else:
            print(f"Invalid page spec '{part}'. Expected N or N-M.")
            sys.exit(1)
    return sorted(pages)


def pages_to_contiguous_ranges(pages: list[int]) -> list[tuple[int, int]]:
    """
    Convert a sorted list of page numbers into a list of contiguous (start, end)
    ranges. Docling requires a single (start, end) range per convert call, so
    non-contiguous selections are split into multiple calls.

    Example: [88,89,90,95,100,101] → [(88,90), (95,95), (100,101)]
    """
    if not pages:
        return []
    ranges = []
    start = prev = pages[0]
    for p in pages[1:]:
        if p == prev + 1:
            prev = p
        else:
            ranges.append((start, prev))
            start = prev = p
    ranges.append((start, prev))
    return ranges


# ---------------------------------------------------------------------------
# PyMuPDF extraction for selected pages (comparison baseline)
# ---------------------------------------------------------------------------

def extract_pymupdf(pdf_path: Path, pages: list[int]) -> dict:
    """
    Extract plain text and basic stats from selected pages using PyMuPDF.
    Returns a dict with 'markdown' text and 'stats'.

    This is the comparison baseline — not a replacement for the full pipeline.
    """
    lines_out   = []
    table_count = 0    # tables detected via drawing rectangles heuristic
    image_count = 0
    title_lines = []

    with fitz.open(str(pdf_path)) as pdf:
        total_pages = len(pdf)
        valid_pages = [p for p in pages if 1 <= p <= total_pages]
        if len(valid_pages) < len(pages):
            skipped = set(pages) - set(valid_pages)
            print(f"  [pymupdf] WARNING: pages {sorted(skipped)} out of range, skipped")

        for page_num in valid_pages:
            page = pdf[page_num - 1]   # fitz is 0-based

            lines_out.append(f"\n--- PyMuPDF page {page_num} ---\n")

            # Extract text blocks
            for block in page.get_text("blocks"):
                text = block[4].strip()
                if not text:
                    continue
                lines_out.append(text)

                # Heuristic: short all-caps lines are likely headings
                if len(text) < 80 and text.isupper():
                    title_lines.append(text)

            # Count images
            image_count += len(page.get_images())

            # Heuristic table detection: pages with many horizontal lines
            drawings = page.get_drawings()
            h_lines = [d for d in drawings if d["type"] == "l"
                       and abs(d["rect"].y1 - d["rect"].y0) < 3
                       and (d["rect"].x1 - d["rect"].x0) > 50]
            if len(h_lines) >= 3:
                table_count += 1

    return {
        "markdown":    "\n".join(lines_out),
        "page_count":  len(valid_pages),
        "table_count": table_count,
        "image_count": image_count,
        "title_count": len(title_lines),
        "sample_titles": title_lines[:10],
    }


# ---------------------------------------------------------------------------
# Step 1 — parse CLI arguments
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser(description="Docling selected-pages probe")
parser.add_argument("pdf", help="Path to the PDF file")
parser.add_argument(
    "--pages", type=str, required=True,
    help="Pages to test, e.g. --pages 88-92 or --pages 88-92,95,100-103"
)
parser.add_argument(
    "--tables", action="store_true", default=False,
    help="Enable Docling TableFormer table structure ML (default: OFF)"
)
parser.add_argument(
    "--ocr", action="store_true", default=False,
    help="Enable OCR (default: OFF — caused std::bad_alloc on large PDFs)"
)
args = parser.parse_args()

# Parse and validate page spec
selected_pages = parse_page_spec(args.pages)
if not selected_pages:
    print("No pages specified.")
    sys.exit(1)

pdf_path = Path(args.pdf).resolve()
if not pdf_path.exists():
    print(f"File not found: {pdf_path}")
    sys.exit(1)
if pdf_path.suffix.lower() != ".pdf":
    print(f"Expected a .pdf file, got: {pdf_path.suffix}")
    sys.exit(1)

contiguous_ranges = pages_to_contiguous_ranges(selected_pages)

print(f"[probe] input     : {pdf_path}")
print(f"[probe] pages     : {selected_pages}")
print(f"[probe] ranges    : {contiguous_ranges}  ({len(contiguous_ranges)} Docling call(s))")
print(f"[probe] OCR       : {'ON' if args.ocr else 'OFF'}")
print(f"[probe] tables    : {'ON (TableFormer)' if args.tables else 'OFF'}")

# ---------------------------------------------------------------------------
# Step 2 — set up output directory
# ---------------------------------------------------------------------------
output_dir = Path(__file__).parent / "output" / "docling_selected_pages" / pdf_path.stem
output_dir.mkdir(parents=True, exist_ok=True)
print(f"[probe] output    : {output_dir}")

# ---------------------------------------------------------------------------
# Step 3 — configure Docling converter
# ---------------------------------------------------------------------------
pipeline_options = PdfPipelineOptions()
pipeline_options.do_ocr             = args.ocr
pipeline_options.do_table_structure = args.tables

converter = DocumentConverter(
    format_options={
        InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
    }
)

# ---------------------------------------------------------------------------
# Step 4 — run Docling on each contiguous range and merge results
# ---------------------------------------------------------------------------
# Docling takes a single (start, end) page_range per call. Non-contiguous
# selections are handled by making one call per contiguous block and merging
# the markdown output. The last call's JSON is saved as representative output.

print("[probe] running Docling ...")
docling_start = time.perf_counter()

all_md_parts  = []
all_titles    = []
all_tables    = []
all_images    = []
last_doc_dict = None

for seg_start, seg_end in contiguous_ranges:
    label = f"pages {seg_start}–{seg_end}" if seg_start != seg_end else f"page {seg_start}"
    print(f"  [docling] converting {label} ...")

    result = converter.convert(
        str(pdf_path),
        page_range=(seg_start, seg_end),
    )
    doc: DoclingDocument = result.document

    # Collect markdown for this segment
    seg_md = doc.export_to_markdown()
    all_md_parts.append(f"\n\n<!-- Docling: {label} -->\n\n{seg_md}")

    # Save dict for JSON output (last segment wins — representative sample)
    last_doc_dict = doc.export_to_dict()

    # Collect stats from this segment
    for item, _level in doc.iterate_items():
        label_str = str(getattr(item, "label", "")).lower()

        if label_str in ("title", "section_header"):
            text = (getattr(item, "text", "") or "").strip()
            if text:
                all_titles.append(text)

        elif label_str == "table":
            table_data = getattr(item, "data", None)
            if table_data is not None:
                try:
                    all_tables.append({
                        "rows": table_data.num_rows,
                        "cols": table_data.num_cols,
                        "pages": f"{seg_start}–{seg_end}",
                    })
                except AttributeError:
                    all_tables.append({"rows": None, "cols": None, "pages": f"{seg_start}–{seg_end}"})
            else:
                all_tables.append({
                    "rows": "unknown", "cols": "unknown",
                    "pages": f"{seg_start}–{seg_end}",
                    "note": "use --tables for row/col counts",
                })

        elif label_str in ("picture", "figure"):
            all_images.append({"pages": f"{seg_start}–{seg_end}"})

docling_elapsed = time.perf_counter() - docling_start
print(f"[probe] Docling complete — {docling_elapsed:.1f}s")

# ---------------------------------------------------------------------------
# Step 5 — run PyMuPDF on the same pages (comparison baseline)
# ---------------------------------------------------------------------------
print("[probe] running PyMuPDF for comparison ...")
pymupdf_start = time.perf_counter()
pymupdf_result = extract_pymupdf(pdf_path, selected_pages)
pymupdf_elapsed = time.perf_counter() - pymupdf_start
print(f"[probe] PyMuPDF complete — {pymupdf_elapsed:.2f}s")

# ---------------------------------------------------------------------------
# Step 6 — save Docling markdown output
# ---------------------------------------------------------------------------
docling_md_path = output_dir / "docling_output.md"
docling_md_path.write_text("\n".join(all_md_parts), encoding="utf-8")
print(f"[probe] saved {docling_md_path.name}")

# ---------------------------------------------------------------------------
# Step 7 — save Docling JSON output (last segment)
# ---------------------------------------------------------------------------
docling_json_path = output_dir / "docling_output.json"
if last_doc_dict is not None:
    docling_json_path.write_text(
        json.dumps(last_doc_dict, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[probe] saved {docling_json_path.name}")

# ---------------------------------------------------------------------------
# Step 8 — save PyMuPDF comparison output
# ---------------------------------------------------------------------------
pymupdf_md_path = output_dir / "pymupdf_output.md"
pymupdf_md_path.write_text(pymupdf_result["markdown"], encoding="utf-8")
print(f"[probe] saved {pymupdf_md_path.name}")

# ---------------------------------------------------------------------------
# Step 9 — build and save summary.json
# ---------------------------------------------------------------------------
notes = []

if not args.tables:
    notes.append("TableFormer OFF — table row/col counts unknown (use --tables)")
if not args.ocr:
    notes.append("OCR OFF — text inside raster images not extracted")
if args.tables and all_tables:
    flat = [t for t in all_tables if t.get("rows") == 1 and t.get("cols") == 1]
    if len(flat) == len(all_tables):
        notes.append(
            "WARNING: all Docling tables are 1×1 even with --tables ON — "
            "TableFormer could not parse structure (borderless or image-based tables)"
        )
    elif flat:
        notes.append(
            f"{len(flat)} of {len(all_tables)} Docling tables are 1×1 — "
            "partial structure failure"
        )

# Comparison note: did Docling find more tables than PyMuPDF?
if len(all_tables) > pymupdf_result["table_count"]:
    notes.append(
        f"Docling found more tables ({len(all_tables)}) than PyMuPDF heuristic "
        f"({pymupdf_result['table_count']}) — Docling may be better for tables here"
    )
elif pymupdf_result["table_count"] > len(all_tables):
    notes.append(
        f"PyMuPDF heuristic found more table-like pages ({pymupdf_result['table_count']}) "
        f"than Docling ({len(all_tables)})"
    )

summary = {
    "source_file":              str(pdf_path),
    "pages_requested":          args.pages,
    "pages_expanded":           selected_pages,
    "page_count":               len(selected_pages),
    "ocr_enabled":              args.ocr,
    "table_structure_enabled":  args.tables,

    # Docling results
    "docling": {
        "runtime_seconds":      round(docling_elapsed, 2),
        "detected_titles_count": len(all_titles),
        "detected_tables_count": len(all_tables),
        "detected_images_count": len(all_images),
        "sample_titles":         all_titles[:10],
        "sample_tables":         all_tables[:5],
    },

    # PyMuPDF results (comparison baseline)
    "pymupdf": {
        "runtime_seconds":      round(pymupdf_elapsed, 3),
        "detected_titles_count": pymupdf_result["title_count"],
        "detected_tables_count": pymupdf_result["table_count"],
        "detected_images_count": pymupdf_result["image_count"],
        "sample_titles":         pymupdf_result["sample_titles"],
    },

    "notes": notes,

    # Question to answer after reviewing the output files
    "evaluation_question": (
        "After reviewing docling_output.md vs pymupdf_output.md, decide: "
        "should Docling be used as (1) fallback only, (2) table enhancer only, "
        "(3) selected-page enhancer, or (4) not useful enough?"
    ),
}

summary_path = output_dir / "summary.json"
summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"[probe] saved {summary_path.name}")

# ---------------------------------------------------------------------------
# Step 10 — print comparison to stdout
# ---------------------------------------------------------------------------
print()
print("=" * 60)
print("COMPARISON SUMMARY")
print("=" * 60)
print(f"  pages tested : {selected_pages}")
print()
print(f"  {'':20s}  {'Docling':>10s}  {'PyMuPDF':>10s}")
print(f"  {'runtime (s)':20s}  {docling_elapsed:>10.1f}  {pymupdf_elapsed:>10.3f}")
print(f"  {'titles':20s}  {len(all_titles):>10d}  {pymupdf_result['title_count']:>10d}")
print(f"  {'tables':20s}  {len(all_tables):>10d}  {pymupdf_result['table_count']:>10d}")
print(f"  {'images':20s}  {len(all_images):>10d}  {pymupdf_result['image_count']:>10d}")
print()
if notes:
    for note in notes:
        print(f"  NOTE : {note}")
print()
print(f"Output saved to: {output_dir}")
print()
print("Next step: open docling_output.md and pymupdf_output.md side by side")
print("and decide which extractor produces better results for these pages.")
