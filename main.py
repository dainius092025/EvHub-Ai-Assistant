"""
main.py — Pipeline orchestration only. No logic lives here.

Pipeline order:
  1. detector.py   — document identity → shared_profile.json
  2. extractor.py  — raw content → raw/*.json + images/
  3. validator.py  — validate raw output
  4. classifier.py — tag elements → classified/*.json
  5. validator.py  — validate classified output
  6. splitter.py   — ownership routing → updates shared_profile + classified

Usage:
  python main.py
  python main.py PDF/evb.pdf
"""

from __future__ import annotations
import logging, sys
from pathlib import Path

from detector   import run as detect
from extractor  import run as extract,  Config as ExtractorConfig
from classifier import run as classify
from validator  import run as validate
from splitter   import run as split

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger("main")


# ── Configuration ─────────────────────────────────────────────────────────────

PDF_FILE   = sys.argv[1] if len(sys.argv) > 1 else "PDF/evb.pdf"
RAW_DIR    = "raw"
OUTPUT_DIR = "output"

EXTRACTOR_CFG = ExtractorConfig()   # all defaults come from config.py


# ── Pipeline ──────────────────────────────────────────────────────────────────

def main() -> None:
    log.info("══════════════════════════════════════")
    log.info("  EV Manual Adapter — Nissan")
    log.info("  PDF: %s", PDF_FILE)
    log.info("══════════════════════════════════════")

    # Step 1 — Detect
    log.info("─── Step 1/6  Detection")
    if not detect(pdf_path=PDF_FILE, output_dir=RAW_DIR):
        log.error("Detection failed — stopping"); return

    # Step 2 — Extract
    log.info("─── Step 2/6  Extraction")
    if not extract(pdf_path=PDF_FILE, output_dir=RAW_DIR, cfg=EXTRACTOR_CFG):
        log.error("Extraction failed — stopping"); return

    # Step 3 — Validate raw
    log.info("─── Step 3/6  Validation (raw)")
    if not validate(input_dir=RAW_DIR, stage="raw", output_dir=RAW_DIR):
        log.error("Raw validation failed — stopping"); return

    # Step 4 — Classify
    log.info("─── Step 4/6  Classification")
    if not classify(raw_dir=RAW_DIR, output_dir=OUTPUT_DIR):
        log.error("Classification failed — stopping"); return

    # Step 5 — Validate classified
    log.info("─── Step 5/6  Validation (classified)")
    if not validate(input_dir=OUTPUT_DIR, stage="classified", output_dir=OUTPUT_DIR):
        log.error("Classified validation failed — stopping"); return

    # Step 6 — Split
    log.info("─── Step 6/6  Content routing")
    if not split(classified_dir=OUTPUT_DIR, raw_dir=RAW_DIR):
        log.error("Splitting failed — stopping"); return

    log.info("══════════════════════════════════════")
    log.info("  Pipeline complete")
    log.info("  Profile:    %s/shared_profile.json", RAW_DIR)
    log.info("  Output:     %s/", OUTPUT_DIR)
    log.info("  Reports:    validation_report_*.json")
    log.info("══════════════════════════════════════")


if __name__ == "__main__":
    main()