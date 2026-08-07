"""
config.py — single source of truth for all pipeline configuration
All Nissan-specific patterns, thresholds, and mappings live here.
No magic strings or hardcoded values anywhere else in the pipeline.

Import this module in detector, extractor, classifier, splitter, validator.
"""

from __future__ import annotations
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────

BASE_DIR       = Path(__file__).parent
SCHEMA_DIR     = BASE_DIR          # schema files live in the project root
OUTPUT_DIR     = BASE_DIR / "output"

SCHEMA_SHARED_PROFILE  = SCHEMA_DIR / "shared_profile.schema.json"
SCHEMA_CLASSIFIED      = SCHEMA_DIR / "classified_batch.schema.json"


# ── Extraction ────────────────────────────────────────────────────────────────

BATCH_SIZE             = 10      # pages per batch — lower to 3 if RAM is tight
PAGE_RENDER_DPI        = 150    # DPI for vector image rendering
MIN_IMAGE_SIZE_PX      = 200     # images smaller than this are discarded
FOOTER_HEIGHT_PCT      = 0.04   # bottom 4% of page = footer region
HEADER_HEIGHT_PCT      = 0.04   # top 4% of page = header region
OCR_THRESHOLD_CHARS    = 100    # chars per page below this → scanned page


# ── Nissan document identity ──────────────────────────────────────────────────

# Maps Nissan section codes found in footers to human-readable names
NISSAN_SECTION_NAMES: dict[str, str] = {
    "HA":  "Heater and Air Conditioning System",
    "EVB": "EV Battery System",
    "VC":  "Vehicle Charging System",
    "GI":  "General Information",
    "EVC": "EV Control System",
    "BRC": "Brake Control System",
    "STR": "Steering System",
    "AX":  "Axle and Suspension",
    "DLK": "Door Lock System",
    "HAC": "Heater and Air Conditioning Control",
    "PG":  "Power Generation and Starting System",
    "CHG": "Charging System",
}

# Nissan footer page reference pattern: HA-34, EVB-5, GI-7
NISSAN_PAGE_REF_PATTERN = r"\b([A-Z]{1,5}-\d{1,4})\b"

# Year extraction pattern
YEAR_PATTERN = r"\b(20\d{2}|19\d{2})\b"

# Known EV model keywords for Nissan
NISSAN_EV_MODELS = ["LEAF", "ARIYA"]

# All Nissan keywords used for manufacturer detection
NISSAN_KEYWORDS = ["NISSAN", "LEAF", "ARIYA", "PATHFINDER", "ALTIMA"]


# ── Nissan noise patterns (classifier uses these) ─────────────────────────────

# Single capital letters on right margin — navigation tabs
SIDEBAR_TAB_X_THRESHOLD = 560   # pixels from left — anything right of this is a tab

# Inline symbols that are visual noise, never content
NOISE_SYMBOLS = frozenset({
    "•", "·", "○", "●", "◆", "■", "□", "–", "—", ">>", "×",
})

# INFOID codes embedded in page content — always noise
INFOID_PATTERN = r"^INFOID:\d+$"

# Variant tags e.g. [WITH HEAT PUMP SYSTEM]
VARIANT_TAG_PATTERN = r"^\[.{5,60}\]$"

# Breadcrumb navigation tags e.g. < REMOVAL AND INSTALLATION >
BREADCRUMB_PATTERN = r"^<\s*.+\s*>$"

# TOC dot-leader lines e.g. "PRECAUTION .............. 4"
TOC_LINE_PATTERN = r"\.{4,}\s*\d+\s*$"

# Image reference codes embedded in table cells e.g. AC359A, JMIA2634GB
IMAGE_REF_PATTERN = r"\s*\b[A-Z]{2,5}\d{3,6}[A-Z]{0,3}\b"

# Running headers — exact section name repeated at top of every page
# Detected by comparing text to header_text_raw from page_map
# No pattern needed — comparison is string equality


# ── Safety level triggers (classifier uses these) ────────────────────────────

SAFETY_TRIGGERS: dict[str, frozenset[str]] = {
    "HIGH_VOLTAGE": frozenset({
        "high voltage", "high-voltage", "hv ", "electric shock",
        "electrocution", "400v", "300v", "lithium", "battery pack",
        "do not touch", "insulated gloves", "service plug",
        "high voltage system", "hv system",
    }),
    "CAUTION": frozenset({
        "caution", "hot surface", "burn", "pressure",
    }),
    "WARNING": frozenset({
        "warning", "danger", "death", "injury", "fire", "explosion",
    }),
}

# Element type classification keywords
WARNING_KEYWORDS  = frozenset({"warning:", "caution:", "danger:"})
NOTE_KEYWORD      = "note:"
HEADER_KEYWORDS   = frozenset({"important:", "precaution"})

# Step patterns
NUMBERED_STEP_PATTERN = r"^\s*(\d+\.|[a-z]\))\s+"
DASH_STEP_PATTERN     = r"^\s*[–\-]\s+\S"

# Specification value pattern — number followed by unit
SPEC_PATTERN = r"\d+\s*(v|a|nm|rpm|°c|°f|kpa|psi|mm|in|kg|lb)\b"


# ── Table repair thresholds (classifier uses these) ───────────────────────────

# Minimum fraction of empty cells in a column to trigger forward-fill
FORWARD_FILL_THRESHOLD = 0.2

# Minimum fraction of rows with dot-leaders to classify as TOC table
TOC_TABLE_THRESHOLD = 0.5

# Image size thresholds for subtype detection
SAFETY_ICON_MAX_PX    = 80    # below this in both dimensions → safety_icon
EXPLODED_VIEW_MIN_PX  = 300   # above this in both dimensions → exploded_view


# ── DTC detection rules (splitter uses these) ─────────────────────────────────
#
# Used by splitter.py to determine whether a page is DTC content.
# Weighted scoring — if total score exceeds DTC_CONFIDENCE_THRESHOLD
# the page is classified as DTC and ownership assigned to dtc_adapter.
#
# DO NOT add DTC logic in classifier.py — all rules live here.

DTC_CONFIDENCE_THRESHOLD = 0.7   # score above this → DTC page

DTC_SIGNALS: list[dict] = [
    # High-confidence signals — structural position in document
    {
        "name":   "breadcrumb_dtc",
        "desc":   "Breadcrumb tag contains DTC/CIRCUIT DIAGNOSIS",
        "weight": 0.50,
    },
    {
        "name":   "heading_dtc",
        "desc":   "Section heading contains DTC/CIRCUIT DIAGNOSIS or DTC Logic",
        "weight": 0.45,
    },
    # Medium-confidence signals — content pattern
    {
        "name":   "table_header_consult",
        "desc":   "Table has header containing CONSULT screen items",
        "weight": 0.25,
    },
    {
        "name":   "table_header_dtc",
        "desc":   "Table has header named DTC",
        "weight": 0.20,
    },
    {
        "name":   "heading_dtc_code",
        "desc":   "Page heading IS a DTC code e.g. P0A0D HV SYSTEM INTERLOCK ERROR",
        "weight": 0.35,
    },
    # Low-confidence signals — content mention, not structure
    {
        "name":   "inline_dtc_code",
        "desc":   "DTC code pattern found in body text",
        "weight": 0.10,
    },
]

# Keyword lists used by each signal above
DTC_BREADCRUMB_KEYWORDS = ["DTC/CIRCUIT DIAGNOSIS", "DTC/CIRCUIT"]
DTC_HEADING_KEYWORDS    = [
    "DTC/CIRCUIT DIAGNOSIS",
    "DTC DETECTION LOGIC",
    "DTC CONFIRMATION PROCEDURE",
    "DIAGNOSIS PROCEDURE",
    "FAIL-SAFE",
    "DTC Logic",
    "DTC Index",
]
DTC_TABLE_HEADERS = [
    "DTC",
    "CONSULT screen items",
    "CONSULT screen item",
    "Possible causes",
    "Possible cause",
    "DTC detecting condition",
]

# Standard OBD-II DTC code pattern
# Matches P0A0D, P338D, U1000 etc.
DTC_CODE_PATTERN = r"\b[PCBU][0-9A-F]{4}\b"

# Page heading that IS a DTC code and title
# e.g. "P0A0D HV SYSTEM INTERLOCK ERROR"
DTC_HEADING_CODE_PATTERN = r"^[PCBU][0-9A-F]{4}\b"


# ── Structural authority priority ─────────────────────────────────────────────
# Used by detector.py to determine primary_source

STRUCTURAL_AUTHORITY_PRIORITY = [
    "internal_outline",   # PDF bookmarks — most reliable
    "visual_toc",         # Parsed TOC page text
    "footer_pattern",     # Footer page reference regex
    "sequential",         # PDF page index — always available, least informative
]