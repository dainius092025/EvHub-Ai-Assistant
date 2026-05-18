"""
pipeline.py
===========
Entry point — scans the manuals/ folder and processes every pdf found

Usage:
    python src/pipeline.py                             # process all PDFs, skip existing output
    python src/pipeline.py --force                     # reprocess all PDFs, overwrite existing output
    python src/pipeline.py manuals/EVB.pdf             # process one PDF, skip if already done
    python src/pipeline.py manuals/EVB.pdf --force     # force reprocess one PDF

Output modes:
    (default)                    importer-oriented output — raw_rows, reconstructed_rows,
                                 reconstruction metadata, cleaned_text. No rendered strings.
    --full                       human-readable output — adds raw_text, raw_table_text,
                                 cleaned_table_text, ocr_used. Use for debugging or inspection.

Examples:
    python src/pipeline.py manuals/EVB.pdf                 # single PDF, importer-ready output
    python src/pipeline.py                                  # all PDFs, importer-ready output
    python src/pipeline.py manuals/EVB.pdf --force         # reprocess + importer-ready output
    python src/pipeline.py manuals/EVB.pdf --full          # single PDF, human-readable output
"""

import argparse
import json
import re
import sys
import fitz
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from shared.document_id import compute_document_id
from shared.validate_output import validate_shared_profile
from extractor import extract_records
from pdf_profile import profile_pdf
from vehicle_info import extract_vehicle_info
from content_extractor import read_page_ref


def _apply_slim(result: dict) -> dict:
    """
    Default output mode — importer-oriented, machine-readable.

    Strips human-readable helper fields that are derivable from source-of-truth fields.
    The importer should use raw_rows (and reconstructed_rows when present) directly —
    not rendered strings.

    Pass --full to include all fields for human inspection or debugging.

    Removed (rendered/helper fields — not needed by importer):
      sections[].raw_text            — raw uncleaned zone text
      tables[].raw_table_text        — rendered string of raw_rows
      tables[].cleaned_table_text    — pipe-formatted cleaned view
      tables[].extraction.ocr_used   — always False for digital PDFs

    Kept (importer needs all of these):
      sections[].cleaned_text        — noise-filtered section text
      tables[].raw_rows              — source of truth: true extraction output
      tables[].reconstructed_rows    — carry-forward filled rows (if present)
      tables[].reconstruction        — metadata: what was inferred and why (if present)
      tables[].extraction            — quality flags, confidence, header hints
    """
    import copy
    result = copy.deepcopy(result)
    for record in result.get("records", []):
        for section in record.get("sections", []):
            section.pop("raw_text", None)
        for table in record.get("tables", []):
            table.pop("raw_table_text", None)
            table.pop("cleaned_table_text", None)
            table.get("extraction", {}).pop("ocr_used", None)
    return result


def _build_canonical_stem(pdf_path: Path, metadata: dict) -> str:
    """
    Build a canonical output stem from vehicle metadata extracted from the PDF.

    Format:  {make}_{model}_{year}_{section}
    Example: nissan_leaf_2013_evb

    Each part is lowercased and non-alphanumeric characters are collapsed to
    underscores — so "MODEL 3" becomes "model_3" and "E-TRON" becomes "e_tron".

    Falls back to pdf_path.stem (the original filename without extension) if
    vehicle extraction fails or returns no usable fields.
    """
    def _slug(text: str) -> str:
        # lowercase, collapse runs of non-alphanumeric characters to one underscore
        return re.sub(r'[^a-z0-9]+', '_', text.lower()).strip('_')

    try:
        # extract make / model / year from footer, foreword, or lookup table
        vehicle = extract_vehicle_info(pdf_path, metadata)
        make  = _slug(vehicle.get("make")  or "")
        model = _slug(vehicle.get("model") or "")
        year  = _slug(vehicle.get("year")  or "")

        # get section code from the first page footer ref  e.g. "EVB-1" → "evb"
        # only use it when there is exactly one section — merged PDFs have many sections
        # and a section suffix in the name would be misleading
        section = ""
        with fitz.open(str(pdf_path)) as pdf:
            if len(pdf) > 0:
                ref = read_page_ref(pdf[0])   # returns e.g. "EVB-1" or None
                if ref and '-' in ref:
                    section = _slug(ref.split('-')[0])

        # only include parts that are non-empty
        parts = [p for p in [make, model, year, section] if p]
        if parts:
            return "_".join(parts)

    except Exception:
        pass  # any failure → fall back silently

    # fallback: use the original PDF filename stem as-is
    return pdf_path.stem.lower()


def _validate_and_warn(data: dict, filename: str) -> None:
    """
    Validate data against shared_profile.schema.json.
    Prints any errors prominently but does not block the write —
    the file is still saved so it can be inspected.
    """
    errors = validate_shared_profile(data)
    if errors:
        print(f"  WARNING — schema validation failed for {filename} ({len(errors)} error(s)):")
        for err in errors:
            print(f"    {err}")
    else:
        print(f"  Schema: valid")


def main():
    # ── Parse arguments ──────────────────────────────────────────────────
    parser = argparse.ArgumentParser(description="EV PDF Codes Adapter — extract DTC records from workshop manual PDFs")
    parser.add_argument("pdf", nargs="?", type=Path, help="Path to a single PDF to process. If omitted, all PDFs in manuals/ are processed.")
    parser.add_argument("--force", action="store_true", help="Reprocess and overwrite existing output.")
    parser.add_argument("--full", action="store_true", help="Include human-readable helper fields (raw_text, raw_table_text, cleaned_table_text, ocr_used). Default output is importer-oriented.")
    args = parser.parse_args()

    # ── Resolve PDF list ─────────────────────────────────────────────────
    if args.pdf:
        if not args.pdf.exists():
            print(f"File not found: {args.pdf}")
            sys.exit(1)
        if args.pdf.suffix.lower() != ".pdf":
            print(f"Not a PDF file: {args.pdf}")
            sys.exit(1)
        pdf_files = [args.pdf]
    else:
        manuals_dir = Path(__file__).parent.parent / "manuals"
        if not manuals_dir.exists():
            print(f"Manuals folder not found: {manuals_dir}")
            sys.exit(1)
        pdf_files = sorted(manuals_dir.glob("*.pdf"))
        if not pdf_files:
            print("No PDF files found in manuals/")
            sys.exit(1)

    print(f"Found {len(pdf_files)} PDF(s) to process")

    # ── Set up base output directory ──────────────────────────────────────
    # All output (JSON + images) goes into data/ — each PDF gets its own subfolder.
    base_dir = Path(__file__).parent.parent / "data"
    base_dir.mkdir(exist_ok=True)

    # ── Processing report ─────────────────────────────────────────────────
    # collects one entry per PDF — printed at the end and saved to data/
    report = []

    # ── Process each PDF ──────────────────────────────────────────────────
    for pdf_path in pdf_files:
        print(f"\nProcessing: {pdf_path.name}")

        # Build canonical stem from vehicle metadata — e.g. nissan_leaf_2013_evb
        # Falls back to pdf_path.stem if extraction returns no usable fields
        canonical = _build_canonical_stem(pdf_path, profile_pdf(pdf_path)[0])

        # Create a subfolder named after the canonical stem — e.g. data/nissan_leaf_2013_evb/
        out_dir = base_dir / canonical
        out_dir.mkdir(exist_ok=True)

        # ── Skip already processed PDFs (unless --force) ──────────────────
        out_path = out_dir / f"{canonical}.json"
        if out_path.exists() and not args.force:
            print(f"  Already processed - skipping. Use --force to reprocess.")
            continue

        # ── Profile the PDF ───────────────────────────────────────────────────
        # quick check before any heavy extraction — tells us what type of PDF this is
        metadata, pdf_profile = profile_pdf(pdf_path)
        pdf_type = pdf_profile["pdf_type"]
        print(f"  PDF type: {pdf_type}")

        # ── Handle scanned PDFs ───────────────────────────────────────────────
        # scanned PDFs have no text layer — OCR not yet built, so we skip extraction
        # we still write a stub JSON so the file appears in the output with a clear reason
        if pdf_type == "scanned":
            document_id = compute_document_id(pdf_path)  # we compute the document ID for scanned PDFs too, so they can be tracked and identified in the future when OCR is added
            profile_out = {k: v for k, v in pdf_profile.items() if k != "link_count_sample"}
            stub = {
                "schema_version": "1.0",
                "schema_type":    "shared_document_profile",
                "document_id":    document_id,
                "source_file":    pdf_path.name,
                "metadata":       metadata,
                "pdf_profile":    profile_out,
                "vehicle":        None,
                "section": {
                    "code":        None,
                    "name":        None,
                    "manual_type": None,
                },
                "processing": {
                    "adapter_name":           "ev-pdf-codes-adapter",
                    "adapter_schema_version": 5,
                    "extraction_status":      "scanned",
                    "extraction_completed":   False,
                    "errors":                 ["scanned PDF — OCR not yet supported"],
                },
                "records": []
            }
            _validate_and_warn(stub, pdf_path.name)
            tmp_path = out_path.with_suffix(".json.tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(stub, f, indent=2, ensure_ascii=False)
            tmp_path.replace(out_path)
            print(f"  Skipped — stub JSON written to {out_path}")
            report.append({"file": pdf_path.name, "pdf_type": pdf_type, "status": "skipped", "reason": "scanned PDF — OCR not yet supported"})
            continue


        # ── Try to process — skip and log if anything goes wrong ─────────────
        # try/except means: attempt the code inside try — if ANY error occurs,
        # jump to except instead of crashing the whole program.
        # This way one bad PDF never kills the rest of the run.
        try:
            result = extract_records(pdf_path, output_dir=out_dir)

            if not result or not result["records"]:
                print("  No records extracted — writing stub JSON.")
                profile_out = {k: v for k, v in pdf_profile.items() if k != "link_count_sample"}
                stub = {
                    "schema_version": "1.0",
                    "schema_type":    "shared_document_profile",
                    "document_id":    compute_document_id(pdf_path),
                    "source_file":    pdf_path.name,
                    "metadata":       metadata,
                    "pdf_profile":    profile_out,
                    "vehicle":        None,
                    "section": {
                        "code":        None,
                        "name":        None,
                        "manual_type": None,
                    },
                    "processing": {
                        "adapter_name":           "ev-pdf-codes-adapter",
                        "adapter_schema_version": 5,
                        "extraction_status":      "no_content",
                        "extraction_completed":   False,
                        "errors":                 ["no DTC codes found"],
                    },
                    "records": []
                }
                _validate_and_warn(stub, pdf_path.name)
                tmp_path = out_path.with_suffix(".json.tmp")
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(stub, f, indent=2, ensure_ascii=False)
                tmp_path.replace(out_path)
                report.append({"file": pdf_path.name, "pdf_type": pdf_type, "status": "skipped", "reason": "no DTC codes found"})
                continue


            # ── Atomic JSON write ─────────────────────────────────────────────
            # We write to a temporary file first (.json.tmp).
            # Only when the write is fully complete do we rename it to .json.
            # If the program crashes mid-write, the .tmp file is left behind
            # and .json is never created — so the next run will reprocess correctly.
            tmp_path = out_path.with_suffix(".json.tmp")   # e.g. data/EVB/EVB.json.tmp

            output = result if args.full else _apply_slim(result)
            _validate_and_warn(output, pdf_path.name)
            with open(tmp_path, 'w', encoding="utf-8") as f:
                json.dump(output, f, indent=2, ensure_ascii=False)

            tmp_path.replace(out_path)   # instant rename — cannot be interrupted halfway

            record_count   = len(result["records"])
            dtc_code_count = sum(len(r.get("codes", [])) for r in result["records"])
            print(f"  Saved {record_count} records ({dtc_code_count} DTC codes) to {out_path}")
            report.append({
                "file":           pdf_path.name,
                "pdf_type":       pdf_type,
                "status":         "extracted",
                "record_count":   record_count,
                "dtc_code_count": dtc_code_count,
            })


            # ── Quality report ────────────────────────────────────────────────
            records_list = result["records"]

            # Records with no sections extracted (no text found)
            missing_text = [r for r in records_list if not r.get("sections")]

            # Count unique images across all records
            all_images = set()
            for r in records_list:
                for img in r.get("images", []):
                    all_images.add(img["image_path"])
            total_images = len(all_images)

        except Exception as e:
            # Something went wrong with this PDF — print the error and move on.
            # The .json file was never written (atomic write), so next run will retry.
            print(f"  ERROR processing {pdf_path.name}: {e}")
            report.append({"file": pdf_path.name, "pdf_type": pdf_type, "status": "error", "reason": str(e)})


    # ── Processing report ─────────────────────────────────────────────────
    # print summary to terminal and save to data/processing_report.json
    print(f"\n{'-' * 50}")
    print(f"Processing report -- {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'-' * 50}")
    for entry in report:
        status = entry["status"].upper()
        pages  = f"  {entry.get('record_count', 0)} records  {entry.get('dtc_code_count', 0)} DTC codes" if entry["status"] == "extracted" else f"  {entry.get('reason', '')}"
        print(f"  {status:10} {entry['file']}{pages}")

    report_path = base_dir / "processing_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({"run_date": datetime.now().isoformat(), "results": report}, f, indent=2, ensure_ascii=False)
    print(f"\nReport saved to {report_path}")

    # ── Persistent run history ────────────────────────────────────────────
    # Append this run to run_history.json — never overwrite, only grow.
    # Each entry mirrors processing_report.json: run_date + results list.
    history_path = base_dir / "run_history.json"
    history_tmp  = history_path.with_suffix(".json.tmp")

    if history_path.exists():
        with open(history_path, "r", encoding="utf-8") as f:
            history = json.load(f)
    else:
        history = {"runs": []}

    history["runs"].append({
        "run_date": datetime.now().isoformat(),
        "results":  report,
    })

    with open(history_tmp, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)
    history_tmp.replace(history_path)
    print(f"History  saved to {history_path}  ({len(history['runs'])} run(s) total)")


if __name__ == "__main__":
    main()
