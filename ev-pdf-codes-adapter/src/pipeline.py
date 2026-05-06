"""
pipeline.py
===========
Entry point — scans the manuals/ folder and processes every pdf found

Usage:
    python src/pipeline.py                        # process all PDFs, skip existing output
    python src/pipeline.py --force                # reprocess all PDFs, overwrite existing output
    python src/pipeline.py manuals/EVB.pdf        # process one PDF, skip if already done
    python src/pipeline.py manuals/EVB.pdf --force  # force reprocess one PDF
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from shared.document_id import compute_document_id
from extractor import extract_records
from pdf_profile import profile_pdf


def main():
    # ── Parse arguments ──────────────────────────────────────────────────
    parser = argparse.ArgumentParser(description="EV PDF Codes Adapter — extract DTC records from workshop manual PDFs")
    parser.add_argument("pdf", nargs="?", type=Path, help="Path to a single PDF to process. If omitted, all PDFs in manuals/ are processed.")
    parser.add_argument("--force", action="store_true", help="Reprocess and overwrite existing output.")
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
        manuals_dir = Path("manuals")
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
    base_dir = Path("data")
    base_dir.mkdir(exist_ok=True)

    # ── Processing report ─────────────────────────────────────────────────
    # collects one entry per PDF — printed at the end and saved to data/
    report = []

    # ── Process each PDF ──────────────────────────────────────────────────
    for pdf_path in pdf_files:
        print(f"\nProcessing: {pdf_path.name}")

        # Create a subfolder named after the PDF — e.g. data/EVB/
        out_dir = base_dir / pdf_path.stem
        out_dir.mkdir(exist_ok=True)

        # ── Skip already processed PDFs (unless --force) ──────────────────
        out_path = out_dir / f"{pdf_path.stem}.json"
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
                "schema_version":         "1.0",
                "schema_type":            "shared_document_profile",
                "adapter_schema_version": 4,
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
                    "adapter_name":         "ev-pdf-codes-adapter",
                    "extraction_completed": False,
                    "errors":               ["scanned PDF — OCR not yet supported"],
                },
                "records": []
            }
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
                    "schema_version":         "1.0",
                    "schema_type":            "shared_document_profile",
                    "adapter_schema_version": 4,
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
                        "adapter_name":         "ev-pdf-codes-adapter",
                        "extraction_completed": False,
                        "errors":               ["no DTC codes found"],
                    },
                    "records": []
                }
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

            with open(tmp_path, 'w', encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)

            tmp_path.replace(out_path)   # instant rename — cannot be interrupted halfway

            print(f"  Saved {len(result['records'])} records to {out_path}")
            report.append({"file": pdf_path.name, "pdf_type": pdf_type, "status": "extracted", "records": len(result["records"])})


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
        pages  = f"  {entry.get('records', 0)} records" if entry["status"] == "extracted" else f"  {entry.get('reason', '')}"
        print(f"  {status:10} {entry['file']}{pages}")

    report_path = base_dir / "processing_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({"run_date": datetime.now().isoformat(), "results": report}, f, indent=2, ensure_ascii=False)
    print(f"\nReport saved to {report_path}")


if __name__ == "__main__":
    main()
