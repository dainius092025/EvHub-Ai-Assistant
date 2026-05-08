"""
text_parser.py
==============
Utility module for text processing used by content_extractor.py.

Provides:
  - KNOWN_HEADINGS   — registry of section headings and their roles, grouped by manufacturer
  - HEADING_LOOKUP   — normalised lookup dict built from KNOWN_HEADINGS (use this for matching)
  - normalize_heading() — normalise a raw heading string for lookup
  - is_noise()       — detects page-level noise lines to discard
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
#
# display_name  — heading text as it appears in the PDF.
#                 Matching is case-insensitive and whitespace-normalised,
#                 so minor spacing differences in the PDF are handled automatically.
# role          — stored in the section object in the output JSON.
#                 Fixed values: description | dtc_logic | dtc_confirmation_procedure
#                               | diagnosis_procedure | component_inspection
#
# HOW TO ADD A NEW MANUFACTURER
# ─────────────────────────────
# 1. Ask GPT (or check a sample PDF): "What are the DTC section heading names
#    used in <Manufacturer> workshop manuals?"
# 2. Add a group below with a comment marking the manufacturer.
# 3. Map each heading to the closest role from the fixed list above.
# 4. No other code changes needed — HEADING_LOOKUP is built automatically.

KNOWN_HEADINGS = [

    # ── Nissan / Infiniti ─────────────────────────────────────────────────────
    # Confirmed on: 2013 Nissan LEAF (EVB.pdf), 204 codes extracted correctly.
    ("Description",                 "description"),
    ("DTC Logic",                   "dtc_logic"),
    ("DTC Confirmation Procedure",  "dtc_confirmation_procedure"),
    ("Diagnosis Procedure",         "diagnosis_procedure"),
    ("Component Inspection",        "component_inspection"),

    # ── Toyota / Lexus ────────────────────────────────────────────────────────
    # Source: Toyota technical manuals (BEV/PHEV/HEV sections).
    # Not yet confirmed on a real PDF — add more variants once tested.
    ("System Description",          "description"),
    ("Circuit Description",         "description"),
    ("How To Proceed With Troubleshooting", "diagnosis_procedure"),
    ("Problem Symptoms Table",      "dtc_logic"),
    ("Inspection Procedure",        "diagnosis_procedure"),
    ("Check",                       "diagnosis_procedure"),

    # ── Hyundai / Kia ─────────────────────────────────────────────────────────
    # Source: Hyundai/Kia IONIQ, EV6, Niro EV workshop manuals.
    # Not yet confirmed on a real PDF.
    ("DTC Description",             "description"),
    ("DTC Detecting Condition",     "dtc_logic"),
    ("DTC Confirmation Procedure",  "dtc_confirmation_procedure"),  # same as Nissan
    ("Schematic Diagram",           "description"),
    ("Terminal And Connector Inspection", "component_inspection"),
    ("Signal Waveform",             "dtc_logic"),

    # ── Volkswagen / Audi / Skoda / Seat (VAG group) ─────────────────────────
    # Source: VAG workshop system (ELSA/ERWIN). Not yet confirmed on a real PDF.
    ("Function",                    "description"),
    ("Possible Causes",             "dtc_logic"),
    ("Diagnosis",                   "diagnosis_procedure"),
    ("Measuring",                   "diagnosis_procedure"),
    ("Component Location",          "description"),

    # ── BMW / MINI ────────────────────────────────────────────────────────────
    # Source: BMW workshop manuals (iX, i3, i4). Not yet confirmed on a real PDF.
    ("Function Description",        "description"),
    ("Fault Pattern",               "dtc_logic"),
    ("Test Steps",                  "diagnosis_procedure"),
    ("Component Replacement",       "component_inspection"),

    # ── Renault / Dacia ───────────────────────────────────────────────────────
    # Source: Renault ZOE, Kangoo E-Tech workshop manuals.
    # Not yet confirmed on a real PDF.
    ("Fault Finding",               "diagnosis_procedure"),
    ("Conditions For Sending",      "dtc_logic"),
    ("Conditions For Clearing",     "dtc_confirmation_procedure"),

]


def normalize_heading(text: str) -> str:
    """
    Normalise a heading string for lookup:
      - Strip leading/trailing whitespace
      - Collapse internal whitespace runs to a single space
      - Lowercase

    This means "  DTC  Logic  " matches "DTC Logic" in KNOWN_HEADINGS.
    """
    return re.sub(r"\s+", " ", text.strip()).lower()


# Pre-built lookup dict: normalised heading text → (display_name, role)
# Built once at import time from KNOWN_HEADINGS.
# Use this instead of iterating KNOWN_HEADINGS directly.
HEADING_LOOKUP: dict[str, tuple[str, str]] = {
    normalize_heading(display): (display, role)
    for display, role in KNOWN_HEADINGS
}


def is_noise(line: str) -> bool:
    """Return True if this line should be discarded (page header, revision line, etc.)."""
    for pattern in NOISE_PATTERNS:
        if pattern.match(line.strip()):
            return True
    return False
