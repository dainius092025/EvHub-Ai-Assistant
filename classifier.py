"""
classifier.py — Stage 3: Nissan noise removal, element tagging, single output
Reads all raw/*.json batches.
Writes ONE output file: output/{section_code}_classified.json

Responsibilities:
  - Filter Nissan-specific noise
  - Tag every text element with type and safety_level
  - Merge split warning_header + body into single warning element
  - Repair tables: clean image refs, forward/backward fill, detect TOC tables
  - Detect image subtype
  - Assemble all batches into one single classified JSON file

Does NOT:
  - Keep one file per batch in output
  - Determine content ownership (splitter owns that)
  - Validate schema (validator owns that)
  - Modify shared_profile.json
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

_INFOID_RE    = re.compile(config.INFOID_PATTERN)
_VARIANT_RE   = re.compile(config.VARIANT_TAG_PATTERN)
_BREADCRUMB_RE = re.compile(config.BREADCRUMB_PATTERN)
_TOC_LINE_RE  = re.compile(config.TOC_LINE_PATTERN)
_IMG_REF_RE   = re.compile(config.IMAGE_REF_PATTERN)
_STEP_RE      = re.compile(config.NUMBERED_STEP_PATTERN, re.IGNORECASE)
_DASH_STEP_RE = re.compile(config.DASH_STEP_PATTERN)
_SPEC_RE      = re.compile(config.SPEC_PATTERN, re.IGNORECASE)
_TAB_LETTERS  = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
_BATCH_RE     = re.compile(r"^\d+_\d+\.json$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Noise detection ───────────────────────────────────────────────────────────

def _is_tab_letter(el: dict) -> bool:
    text = el.get("text", "").strip()
    if text not in _TAB_LETTERS:
        return False
    bbox = el.get("bbox")
    return bbox is not None and bbox[0] > config.SIDEBAR_TAB_X_THRESHOLD


def _is_noise(el: dict, header_text_raw: str | None) -> bool:
    text = el.get("text", "").strip()
    if not text:                              return True
    if text in config.NOISE_SYMBOLS:          return True
    if _INFOID_RE.match(text):                return True
    if _VARIANT_RE.match(text):               return True
    if _BREADCRUMB_RE.match(text):            return True
    if _TOC_LINE_RE.search(text):             return True
    if _is_tab_letter(el):                    return True
    if (header_text_raw
            and text.strip() == header_text_raw.strip()
            and len(text.strip()) > 3):       return True
    return False


# ── Safety level ──────────────────────────────────────────────────────────────

def _safety_level(text: str) -> str:
    low = text.lower()
    for level, keywords in config.SAFETY_TRIGGERS.items():
        if any(k in low for k in keywords):
            return level
    return "NONE"


# ── Text classification ───────────────────────────────────────────────────────

def _classify_element(el: dict) -> dict:
    text  = el.get("text", "").strip()
    label = el.get("docling_label", "") or ""
    low   = text.lower()

    if any(low.startswith(k) for k in config.WARNING_KEYWORDS):
        t = "warning_header"
    elif low.startswith(config.NOTE_KEYWORD):
        t = "note"
    elif any(k in low for k in config.HEADER_KEYWORDS) or label == "section_header":
        t = "section_header"
    elif _STEP_RE.match(text) or _DASH_STEP_RE.match(text) or label == "list_item":
        t = "procedure_step"
    elif _SPEC_RE.search(text):
        t = "spec_value"
    else:
        t = "general_text"

    return {**el, "type": t, "safety_level": _safety_level(text)}


# ── Warning merge ─────────────────────────────────────────────────────────────

def _process_texts(elements: list[dict], page_map: dict) -> list[dict]:
    header_by_page: dict[int, str] = {
        int(pg): info.get("header_text_raw") or ""
        for pg, info in page_map.items()
    }

    filtered   = [
        el for el in elements
        if not _is_noise(el, header_by_page.get(el.get("page_pdf") or 0, ""))
    ]
    classified = [_classify_element(el) for el in filtered]

    merged = []
    i = 0
    while i < len(classified):
        el = classified[i]
        if el["type"] == "warning_header" and i + 1 < len(classified):
            nxt = classified[i + 1]
            if nxt["type"] != "procedure_step":
                combined = f"{el['text'].strip()} {nxt['text'].strip()}"
                merged.append({
                    **el,
                    "text":         combined,
                    "type":         "warning",
                    "safety_level": _safety_level(combined),
                })
                i += 2
                continue
            else:
                merged.append({**el, "type": "warning",
                               "safety_level": _safety_level(el["text"])})
                i += 1
        else:
            merged.append(el)
            i += 1

    return merged


# ── Table repair ──────────────────────────────────────────────────────────────

def _forward_fill(grid: list[list[str]]) -> list[list[str]]:
    if not grid:
        return grid
    filled = [row[:] for row in grid]
    data   = filled[1:]
    for col in range(len(filled[0]) - 1):
        if not data:
            continue
        empty_count = sum(1 for row in data if not row[col].strip())
        if empty_count / len(data) <= config.FORWARD_FILL_THRESHOLD:
            continue
        last = ""
        for row in data:
            if row[col].strip(): last = row[col]
            else: row[col] = last
        last = ""
        for row in reversed(data):
            if row[col].strip(): last = row[col]
            elif last: row[col] = last
    return filled


def _clean_img_refs(grid: list[list[str]]) -> list[list[str]]:
    return [[_IMG_REF_RE.sub("", cell).strip() for cell in row] for row in grid]


def _grid_to_markdown(grid: list[list[str]]) -> str:
    if not grid:
        return ""
    header = "| " + " | ".join(grid[0]) + " |"
    sep    = "| " + " | ".join(["---"] * len(grid[0])) + " |"
    rows   = ["| " + " | ".join(row) + " |" for row in grid[1:]]
    return "\n".join([header, sep] + rows)


def _is_toc_table(grid: list[list[str]]) -> bool:
    if not grid or len(grid[0]) < 2:
        return False
    dot_count = sum(
        1 for row in grid
        if len(row) > 1 and ("..." in row[1] or row[1].strip() == "")
    )
    return dot_count / len(grid) > config.TOC_TABLE_THRESHOLD


def _process_tables(tables: list[dict]) -> list[dict]:
    result = []
    for table in tables:
        grid = table.get("data_raw") or table.get("data", [])
        if not grid:
            result.append({**table, "table_type": "empty", "data": [], "markdown": ""})
            continue
        if _is_toc_table(grid):
            result.append({**table, "table_type": "toc", "data": grid, "markdown": ""})
            continue
        grid_clean = _clean_img_refs(grid)
        first_col  = [row[0].strip() for row in grid_clean if row]
        is_index   = all(len(v) <= 3 or v == "" for v in first_col)
        n_empty    = sum(1 for row in grid_clean for cell in row[:2] if not cell.strip())
        n_total    = len(grid_clean) * min(2, len(grid_clean[0]))
        is_spec    = n_total > 0 and (n_empty / n_total) > 0.3
        if is_index or is_spec:
            table_type = "index_table" if is_index else "spec_table"
            fixed      = _forward_fill(grid_clean)
        else:
            table_type = "general"
            has_empty  = any(not row[0].strip() for row in grid_clean[1:])
            fixed      = _forward_fill(grid_clean) if has_empty else grid_clean
        result.append({
            **table,
            "table_type": table_type,
            "data":       fixed,
            "data_raw":   grid,
            "markdown":   _grid_to_markdown(fixed),
        })
    return result


# ── Image subtype ─────────────────────────────────────────────────────────────

def _image_subtype(img: dict) -> str:
    w = img.get("width_px") or 0
    h = img.get("height_px") or 0
    if w < config.SAFETY_ICON_MAX_PX and h < config.SAFETY_ICON_MAX_PX:
        return "safety_icon"
    if w >= config.EXPLODED_VIEW_MIN_PX and h >= config.EXPLODED_VIEW_MIN_PX:
        return "exploded_view"
    return "diagram"


# ── Entry point ───────────────────────────────────────────────────────────────

def run(
    raw_dir:    str | Path = "raw",
    output_dir: str | Path = "output",
) -> bool:
    raw_dir    = Path(raw_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load shared profile for document identity
    profile_path = raw_dir / "shared_profile.json"
    profile      = {}
    if profile_path.exists():
        profile = json.loads(profile_path.read_text(encoding="utf-8"))

    section_code = profile.get("section", {}).get("code") or "UNKNOWN"
    document_id  = profile.get("document_id")

    # Check output file doesn't already exist
    out_file = output_dir / f"{section_code}_classified.json"
    if out_file.exists():
        log.info("Output already exists: %s — skipping", out_file)
        return True

    # Load all batch files in order
    batches = sorted(
        [f for f in raw_dir.glob("*.json") if _BATCH_RE.match(f.name)],
        key=lambda p: int(p.stem.split("_")[0]),
    )

    if not batches:
        log.error("No batch files found in %s", raw_dir)
        return False

    log.info("Classifying %d batches → %s", len(batches), out_file.name)

    # Accumulate across all batches
    all_texts:    list[dict] = []
    all_tables:   list[dict] = []
    all_images:   list[dict] = []
    all_page_map: dict       = {}
    ocr_used      = False
    first_batch   = None

    for batch_path in batches:
        try:
            raw = json.loads(batch_path.read_text(encoding="utf-8"))
        except Exception:
            log.exception("Failed to read %s", batch_path.name)
            return False

        if first_batch is None:
            first_batch = raw

        page_map = raw.get("page_map", {})
        all_page_map.update(page_map)

        if raw.get("batch", {}).get("ocr_used"):
            ocr_used = True

        # Process this batch
        texts  = _process_texts(raw.get("text_elements", []), page_map)
        tables = _process_tables(raw.get("tables", []))
        images = [{**img, "subtype": _image_subtype(img)}
                  for img in raw.get("images", [])]

        all_texts.extend(texts)
        all_tables.extend(tables)
        all_images.extend(images)

    # Build single output document
    out_doc = {
        "schema_version": "2.0",
        "schema_type":    "classified_batch",
        "document_id":    document_id,
        "manufacturer":   profile.get("vehicle", {}).get("make"),
        "model":          profile.get("vehicle", {}).get("model"),
        "year":           profile.get("vehicle", {}).get("year"),
        "section_code":   section_code,
        "batch": {
            "page_start_pdf":    1,
            "page_end_pdf":      profile.get("section", {}).get("page_count"),
            "ocr_used":          ocr_used,
            "tableformer_used":  True,
            "extracted_at":      first_batch.get("batch", {}).get("extracted_at") if first_batch else None,
            "classified_at":     _now(),
            "extraction_errors": [],
        },
        "page_map":      all_page_map,
        "text_elements": all_texts,
        "tables":        all_tables,
        "images":        all_images,
    }

    out_file.write_text(
        json.dumps(out_doc, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    log.info(
        "Written: %s  text=%d  tables=%d  images=%d",
        out_file.name, len(all_texts), len(all_tables), len(all_images),
    )
    return True


if __name__ == "__main__":
    run(raw_dir="raw", output_dir="output")