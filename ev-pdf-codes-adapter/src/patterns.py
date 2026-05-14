import re

# Matches DTC codes like P0A0D, B1234, C3456, U0100
CODE_RE = re.compile(r"^[PBCU][0-9A-F]{4}$", re.IGNORECASE)

# Matches EVB-123 style references
REF_RE = re.compile(r"[A-Z]{2,10}-(\d+)", re.IGNORECASE)

# Single uppercase letters on their own line — PDF sidebar nav tabs (A, B, C…)
# Deliberately limited to one letter so decision labels (YES, NO) are preserved.
SIDEBAR_RE = re.compile(r"^\s*[A-Z]\s*$", re.MULTILINE)

# Internal Nissan reference IDs
INFOID_RE = re.compile(r"INFOID:\d+")

# Known heading names for the DTC index page across manufacturers.
# Each entry is the normalised (lowercase, stripped) first line of the heading block.
# Risky / ambiguous headings (e.g. "applicable dtc", "dtc detection logic") are
# intentionally excluded — they appear on individual DTC record pages, not the index.
DTC_INDEX_HEADINGS: frozenset[str] = frozenset({
    # Generic / most common
    "dtc index",
    "dtc list",
    "dtc table",
    "dtc chart",
    "dtc lookup table",
    "dtc inspection index",
    # Formal names
    "diagnostic trouble code list",
    "diagnostic trouble code chart",
    "diagnostic trouble code index",
    "trouble code list",
    # European OEMs (VW, BMW, etc.)
    "fault code list",
    "fault code table",
    # Generic non-OEM
    "error code list",
    # Nissan / Toyota self-diagnosis style
    "self-diagnosis results",
    "self-diagnostic results",
    # Hybrid troubleshooting layout
    "symptom/dtc index",
})

# Strict subset of DTC_INDEX_HEADINGS used for PDF bookmark matching only.
# Bookmark entries can point to subsection headings inside content pages
# (e.g. a "Self-diagnostic results" bookmark inside a system description page).
# Using the full DTC_INDEX_HEADINGS set for bookmarks causes false positives.
# This stricter set only includes headings that unambiguously identify a
# standalone DTC index page — not a subsection within a content page.
DTC_INDEX_HEADINGS_STRICT: frozenset[str] = frozenset({
    "dtc index",
    "dtc list",
    "dtc table",
    "dtc chart",
    "dtc lookup table",
    "dtc inspection index",
    "diagnostic trouble code list",
    "diagnostic trouble code chart",
    "diagnostic trouble code index",
    "trouble code list",
    "fault code list",
    "fault code table",
    "error code list",
    "symptom/dtc index",
    # self-diagnosis results intentionally excluded —
    # too ambiguous for bookmarks (appears as subsection in content pages)
})

# Generic image/figure identifier — uppercase letters + digits, no spaces, 6–20 chars.
# Matches OEM figure codes like JSCIA0812GB, JPCIA0347ZZ without hardcoding any brand.
# Rule: starts with 1–8 uppercase letters, then 2+ digits, then 0–8 more alphanumeric chars.
IMAGE_ID_RE = re.compile(r'^[A-Z]{1,8}[0-9]{2,}[A-Z0-9]{0,8}$')