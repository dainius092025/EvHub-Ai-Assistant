"""
main.py — Pipeline orchestration only. No logic lives here.

Pipeline order:
  1. detector.py          — document identity → raw/shared_profile.json
  2. extractor.py         — raw content → raw/*.json + raw/images/
  3. classifier.py        — noise removal + element tagging → output/{SECTION}_classified.json
  4. contents_parser.py   — PDF outline → raw/section_map.json
  5. section_classifier.py — assign elements to sections → output/{SECTION}_sectioned.json
  6. validator.py         — advisory validation of final output

Notes:
  - splitter.py is Phase 3 (DTC boundary routing). Not wired here.
  - chunker.py and assembler.py are Phase 2. Not wired here.
  - Validation is advisory — a validation failure logs warnings but does
    not stop the pipeline. The sectioned output is still usable.

Usage:
  python main.py
  python main.py PDF/evb.pdf
"""

from __future__ import annotations
import logging, sys
from pathlib import Path

from detector            import run as detect
from extractor           import run as extract,  Config as ExtractorConfig
from classifier          import run as classify
from contents_parser     import run as parse_contents
from section_classifier  import run as structure
from validator           import run as validate

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger("main")


# ── Configuration ─────────────────────────────────────────────────────────────

PDF_FILE   = sys.argv[1] if len(sys.argv) > 1 else "PDF/vc.pdf"
RAW_DIR    = "raw"
OUTPUT_DIR = "output"

EXTRACTOR_CFG = ExtractorConfig()   # all defaults from config.py


# ── Pipeline ──────────────────────────────────────────────────────────────────

def main() -> None:
    log.info("══════════════════════════════════════")
    log.info("  EV Manual Adapter — Nissan")
    log.info("  PDF: %s", PDF_FILE)
    log.info("══════════════════════════════════════")

    # Step 1 — Detect document identity
    log.info("─── Step 1/6  Detection")
    if not detect(pdf_path=PDF_FILE, output_dir=RAW_DIR):
        log.error("Detection failed — stopping"); return

    # Step 2 — Extract raw content
    log.info("─── Step 2/6  Extraction")
    if not extract(pdf_path=PDF_FILE, output_dir=RAW_DIR, cfg=EXTRACTOR_CFG):
        log.error("Extraction failed — stopping"); return

    # Step 3 — Classify elements (noise removal + tagging)
    log.info("─── Step 3/6  Classification")
    if not classify(raw_dir=RAW_DIR, output_dir=OUTPUT_DIR):
        log.error("Classification failed — stopping"); return

    # Step 4 — Build section map from PDF outline
    log.info("─── Step 4/6  Contents parsing (section map)")
    if not parse_contents(pdf_path=PDF_FILE, output_dir=RAW_DIR):
        log.error("Contents parsing failed — stopping"); return

    # Step 5 — Assign elements to sections → final output
    log.info("─── Step 5/6  Section classification (structured output)")
    if not structure(raw_dir=RAW_DIR, output_dir=OUTPUT_DIR):
        log.error("Section classification failed — stopping"); return

    # Step 6 — Validate classified output (advisory — does not stop pipeline)
    log.info("─── Step 6/6  Validation (advisory)")
    validate(input_dir=OUTPUT_DIR, stage="classified", output_dir=OUTPUT_DIR)

    log.info("══════════════════════════════════════")
    log.info("  Pipeline complete")
    log.info("  Profile:     %s/shared_profile.json", RAW_DIR)
    log.info("  Section map: %s/section_map.json", RAW_DIR)
    log.info("  Classified:  %s/{SECTION}_classified.json", OUTPUT_DIR)
    log.info("  Final:       %s/{SECTION}_sectioned.json", OUTPUT_DIR)
    log.info("══════════════════════════════════════")


if __name__ == "__main__":
    main()