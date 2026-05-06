"""
text_parser.py
==============
Utility module for text processing used by content_extractor.py.

Provides:
  - KNOWN_HEADINGS  — registry of section headings and their roles
  - is_noise()      — detects page-level noise lines to discard
"""

import re

# ── Noise patterns — lines to ignore completely ───────────────────────────────
# These appear on every page but carry no useful content.
# Rules:
#   - DTC-specific patterns are acceptable (this adapter targets DTC content).
#   - Manufacturer-specific patterns are NOT acceptable — do not add model names
#     or brand-specific strings here.
NOISE_PATTERNS = [
    re.compile(r"^Revision:\s+", re.IGNORECASE),              # e.g. "Revision: 2014 June" — generic revision header
    re.compile(r"^<\s*DTC/CIRCUIT DIAGNOSIS\s*>$", re.IGNORECASE),  # DTC section banner
    re.compile(r"^[A-Z]{2,4}-\d+$"),                          # standalone page refs e.g. "EVB-88"
    re.compile(r"^[PBCU][0-9A-F]{4}\s+[A-Z][A-Z\s]*$"),      # DTC title as page continuation header e.g. "P0A0D HV SYSTEM INTERLOCK ERROR"
    re.compile(r"^\d{4}\s+[A-Z][A-Z\s]*$"),                  # year + model name printed on every page e.g. "2013 LEAF", "2022 IONIQ"
]

# ── Known section headings ────────────────────────────────────────────────────
# Each tuple: (display_name, role)
# display_name   — the heading text as it appears in the PDF (matched case-insensitively)
# role           — stored in the section object in the output JSON
#
# WARNING: these heading names are Nissan-specific.
# Other manufacturers use different heading text for the same concepts.
# This list must be extended per manufacturer before processing non-Nissan PDFs.
# To add support for a new heading, add a tuple here — no other changes needed.
KNOWN_HEADINGS = [
    ("Description",                "description"),
    ("DTC Logic",                  "dtc_logic"),
    ("DTC Confirmation Procedure", "dtc_confirmation_procedure"),
    ("Diagnosis Procedure",        "diagnosis_procedure"),
    ("Component Inspection",       "component_inspection"),
]


def is_noise(line: str) -> bool:
    """Return True if this line should be discarded (page header, revision line, etc.)."""
    for pattern in NOISE_PATTERNS:
        if pattern.match(line.strip()):
            return True
    return False
