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
# These appear on every page but carry no useful content
NOISE_PATTERNS = [
    re.compile(r"^Revision:\s+", re.IGNORECASE),              # e.g. "Revision: 2014 June"
    re.compile(r"^<\s*DTC/CIRCUIT DIAGNOSIS\s*>$", re.IGNORECASE),
    re.compile(r"^\d{4}\s+LEAF$", re.IGNORECASE),             # e.g. "2011 LEAF"
    re.compile(r"^LEAF$", re.IGNORECASE),
    re.compile(r"^[A-Z]{2,4}-\d+$"),                          # standalone page refs e.g. "EVB-88"
]

# ── Known section headings ────────────────────────────────────────────────────
# Each tuple: (display_name, role)
# display_name   — the heading text as it appears in the PDF (matched case-insensitively)
# role           — stored in the section object in the output JSON
# To add support for a new heading, just add a tuple here — no other changes needed.
KNOWN_HEADINGS = [
    ("Description",                "description"),
    ("DTC Logic",                  "dtc_logic"),
    ("DTC Confirmation Procedure", "dtc_confirmation_procedure"),
    ("Diagnosis Procedure",        "diagnosis_procedure"),
]


def is_noise(line: str) -> bool:
    """Return True if this line should be discarded (page header, revision line, etc.)."""
    for pattern in NOISE_PATTERNS:
        if pattern.match(line.strip()):
            return True
    return False
