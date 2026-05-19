"""
classifier.py — Stage 3: Noise removal and element classification
Reads:  raw/{start}_{end}.json  (from extractor.py)
        raw/shared_profile.json (from detector.py)
Writes: output/{SECTION}_classified.json

Responsibilities:
  - Merge all raw batches into a single classified output file
  - Remove noise: INFOID lines, breadcrumbs, variant tags, TOC lines,
    sidebar navigation tabs, bare noise symbols, running headers
  - Classify text elements: assign type and safety_level
  - Classify tables: type (toc/dtc/general), repair merged cells, extract image refs
  - Classify images: assign subtype (safety_icon/exploded_view/diagram)
  - Rename raw field names (data_raw→data, markdown_raw→markdown) for downstream

Does NOT:
  - Assign elements to sections (that is section_classifier.py's job)
  - Read section_map.json
  - Make structural decisions about document hierarchy
"""

from __future__ import annotations
import json, logging, re
from datetime import datetime, timezone
from pathlib import Path

import config

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger("classifier")

_BATCH_RE      = re.compile(r"^\d+_\d+\.json$")
_INFOID_RE     = re.compile(config.INFOID_PATTERN)
_VARIANT_RE    = re.compile(config.VARIANT_TAG_PATTERN)
_BREADCRUMB_RE = re.compile(config.BREADCRUMB_PATTERN)
_TOC_LINE_RE   = re.compile(config.TOC_LINE_PATTERN)
_STEP_NUM_RE   = re.compile(config.NUMBERED_STEP_PATTERN)
_STEP_DASH_RE  = re.compile(config.DASH_STEP_PATTERN)
_SPEC_RE       = re.compile(config.SPEC_PATTERN, re.IGNORECASE)
_IMAGE_REF_RE  = re.compile(config.IMAGE_REF_PATTERN)
_DTC_CODE_RE   = re.compile(config.DTC_CODE_PATTERN)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Noise detection ───────────────────────────────────────────────────────────

def _is_noise(text: str, bbox: list | None, header_texts: set[str]) -> bool:
    """Return True if this text element is structural noise to be removed."""
    stripped = text.strip()
    if not stripped:
        return True
    if stripped in config.NOISE_SYMBOLS:
        return True
    if _INFOID_RE.match(stripped):
        return True
    if _VARIANT_RE.match(stripped):
        return True
    if _BREADCRUMB_RE.match(stripped):
        return True
    if _TOC_LINE_RE.search(stripped):
        return True
    # Single capital letter far right of page = navigation sidebar tab
    if len(stripped) == 1 and stripped.isupper() and bbox and len(bbox) >= 1:
        if float(bbox[0]) > config.SIDEBAR_TAB_X_THRESHOLD:
            return True
    # Running header: exact match to page header_text_raw
    if stripped in header_texts:
        return True
    return False


# ── Text element classification ────────────────────────────────────────────────

def _classify_type(text: str) -> str:
    lower = text.lower().strip()
    for kw in config.WARNING_KEYWORDS:
        if lower.startswith(kw):
            return "warning"
    if lower.startswith(config.NOTE_KEYWORD):
        return "note"
    for kw in config.HEADER_KEYWORDS:
        if lower.startswith(kw):
            return "header"
    if _STEP_NUM_RE.match(text.strip()) or _STEP_DASH_RE.match(text.strip()):
        return "procedure_step"
    if _SPEC_RE.search(lower):
        return "specification"
    return "body"


def _classify_safety(text: str) -> str:
    lower = text.lower()
    for level, triggers in config.SAFETY_TRIGGERS.items():
        if any(t in lower for t in triggers):
            return level
    return "NONE"


# ── Table classification and repair ───────────────────────────────────────────

def _extract_image_refs(data_raw: list[list[str]]) -> list[str]:
    seen: dict[str, None] = {}
    for row in data_raw:
        for cell in row:
            for m in _IMAGE_REF_RE.finditer(cell or ""):
                ref = m.group().strip()
                seen[ref] = None
    return list(seen)


def _is_toc_table(data_raw: list[list[str]]) -> bool:
    if not data_raw:
        return False
    toc_rows = sum(
        1 for row in data_raw
        if any(_TOC_LINE_RE.search(cell or "") for cell in row)
    )
    return (toc_rows / len(data_raw)) >= config.TOC_TABLE_THRESHOLD


def _is_dtc_table(headers: list[str], body: list[list[str]]) -> bool:
    header_lower = {(h or "").strip().lower() for h in headers}
    for dtc_hdr in config.DTC_TABLE_HEADERS:
        if dtc_hdr.lower() in header_lower:
            return True
    for row in body[:5]:
        for cell in row:
            if cell and _DTC_CODE_RE.search(cell):
                return True
    return False


def _forward_fill(col: list[str]) -> list[str]:
    result = list(col)
    last = ""
    for i, v in enumerate(result):
        if v.strip():
            last = v
        else:
            result[i] = last
    return result


def _repair_table(body: list[list[str]]) -> list[list[str]]:
    """Forward-fill columns that are mostly empty (merged-cell pattern)."""
    if not body:
        return body
    n_cols  = max(len(row) for row in body)
    padded  = [row + [""] * (n_cols - len(row)) for row in body]
    repaired = [list(row) for row in padded]
    for col_i in range(n_cols):
        col        = [row[col_i] for row in padded]
        empty_frac = sum(1 for v in col if not v.strip()) / len(col)
        if empty_frac >= config.FORWARD_FILL_THRESHOLD:
            filled = _forward_fill(col)
            for row_i, v in enumerate(filled):
                repaired[row_i][col_i] = v
    return repaired


def _classify_table(tbl: dict) -> dict:
    data_raw = tbl.get("data_raw") or []
    headers  = data_raw[0] if data_raw else []
    body     = data_raw[1:] if len(data_raw) > 1 else []

    if _is_toc_table(data_raw):
        table_type = "toc"
    elif _is_dtc_table(headers, body):
        table_type = "dtc"
    else:
        table_type = "general"

    repaired   = _repair_table(body)
    image_refs = _extract_image_refs(data_raw)

    out = {k: v for k, v in tbl.items() if k not in ("data_raw", "markdown_raw")}
    out.update({
        "table_type":    table_type,
        "headers":       headers,
        "data":          repaired,
        "markdown":      tbl.get("markdown_raw", ""),
        "image_refs":    image_refs,
        "is_dtc":        table_type == "dtc",
        "content_owner": "cars_adapter",
    })
    return out


# ── Image classification ───────────────────────────────────────────────────────

def _classify_image(img: dict) -> dict:
    w = img.get("width_px") or 0
    h = img.get("height_px") or 0

    if w <= config.SAFETY_ICON_MAX_PX and h <= config.SAFETY_ICON_MAX_PX:
        subtype = "safety_icon"
    elif w >= config.EXPLODED_VIEW_MIN_PX and h >= config.EXPLODED_VIEW_MIN_PX:
        subtype = "exploded_view"
    else:
        subtype = "diagram"

    return {**img, "subtype": subtype, "content_owner": "cars_adapter"}


# ── Entry point ───────────────────────────────────────────────────────────────

def run(
    raw_dir:    str | Path = "raw",
    output_dir: str | Path = "output",
) -> bool:
    raw_dir    = Path(raw_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load shared profile for section code and document identity
    profile_path = raw_dir / "shared_profile.json"
    if not profile_path.exists():
        log.error("shared_profile.json not found — run detector.py first")
        return False
    profile      = json.loads(profile_path.read_text(encoding="utf-8"))
    section_code = profile.get("section", {}).get("code") or "UNKNOWN"
    doc_id       = profile.get("document_id")

    # Find and sort all raw batch files
    batch_files = sorted(
        [f for f in raw_dir.glob("*.json") if _BATCH_RE.match(f.name)],
        key=lambda p: int(p.stem.split("_")[0]),
    )
    if not batch_files:
        log.error("No raw batch files found in %s — run extractor.py first", raw_dir)
        return False

    log.info("Classifying %d batch file(s) for section %s", len(batch_files), section_code)

    all_texts:   list[dict] = []
    all_tables:  list[dict] = []
    all_images:  list[dict] = []
    any_ocr      = False
    total_pages  = 0

    for batch_path in batch_files:
        batch    = json.loads(batch_path.read_text(encoding="utf-8"))
        page_map = batch.get("page_map", {})
        total_pages += len(page_map)

        if batch.get("batch", {}).get("ocr_used"):
            any_ocr = True

        # Build running-header text set from page map for this batch
        header_texts: set[str] = {
            info.get("header_text_raw", "").strip()
            for info in page_map.values()
            if info.get("header_text_raw", "").strip()
        }

        # ── Text elements ─────────────────────────────────────────────────────
        kept = dropped = 0
        for el in batch.get("text_elements", []):
            text = (el.get("text") or "").strip()
            if _is_noise(text, el.get("bbox"), header_texts):
                dropped += 1
                continue
            all_texts.append({
                **el,
                "type":         _classify_type(text),
                "safety_level": _classify_safety(text),
            })
            kept += 1
        log.info("  %s: text kept=%d dropped=%d", batch_path.name, kept, dropped)

        # ── Tables ───────────────────────────────────────────────────────────
        for tbl in batch.get("tables", []):
            all_tables.append(_classify_table(tbl))

        # ── Images ───────────────────────────────────────────────────────────
        for img in batch.get("images", []):
            all_images.append(_classify_image(img))

    log.info("Total: text=%d tables=%d images=%d ocr=%s",
             len(all_texts), len(all_tables), len(all_images), any_ocr)

    out = {
        "schema_version": "2.0",
        "schema_type":    "classified_batch",
        "document_id":    doc_id,
        "section_code":   section_code,
        "batch": {
            "total_pages":    total_pages,
            "ocr_used":       any_ocr,
            "classified_at":  _now(),
            "source_batches": [f.name for f in batch_files],
        },
        "text_elements": all_texts,
        "tables":        all_tables,
        "images":        all_images,
    }

    out_path = output_dir / f"{section_code}_classified.json"
    out_path.write_text(
        json.dumps(out, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("Written: %s", out_path)
    return True


if __name__ == "__main__":
    run(raw_dir="raw", output_dir="output")
