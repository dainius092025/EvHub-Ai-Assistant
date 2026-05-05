import re

# Matches DTC codes like P0A0D, B1234, C3456, U0100
CODE_RE = re.compile(r"^[PBCU][0-9A-F]{4}$", re.IGNORECASE)

# Matches EVB-123 style references
REF_RE = re.compile(r"[A-Z]{2,10}-(\d+)", re.IGNORECASE)

# Single letters on their own line — PDF sidebar nav tabs
SIDEBAR_RE = re.compile(r"^\s*[A-Z]{1,3}\s*$", re.MULTILINE)

# Internal Nissan reference IDs
INFOID_RE = re.compile(r"INFOID:\d+")

# Generic image/figure identifier — uppercase letters + digits, no spaces, 6–20 chars.
# Matches OEM figure codes like JSCIA0812GB, JPCIA0347ZZ without hardcoding any brand.
# Rule: starts with 1–8 uppercase letters, then 2+ digits, then 0–8 more alphanumeric chars.
IMAGE_ID_RE = re.compile(r'^[A-Z]{1,8}[0-9]{2,}[A-Z0-9]{0,8}$')