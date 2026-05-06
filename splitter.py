"""
splitter.py — Stage 5: Content ownership routing
Reads classified/*.json — updates page_map with dtc_score and content_owner.
Updates shared_profile.json content_split with page ranges and page_classification.

Responsibilities (only these):
  - Score every page for DTC content using weighted signals from config
  - Assign content_owner to each page: procedure_adapter or dtc_adapter
  - Write page_classification map to shared_profile.json
  - Write page_ranges per adapter to shared_profile.json
  - Stamp is_dtc and content_owner on text elements, tables, images

Does NOT:
  - Filter or remove content (extractor captured everything — it stays)
  - Make semantic chunking decisions
  - Validate schema
  - Modify raw batch files
"""

from __future__ import annotations
import json, logging, re
from pathlib import Path

import config

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger("splitter")

_BATCH_RE    = re.compile(r"^\d+_\d+\.json$")
_DTC_CODE_RE = re.compile(config.DTC_CODE_PATTERN)
_DTC_HEAD_RE = re.compile(config.DTC_HEADING_CODE_PATTERN)


# ── DTC scoring ───────────────────────────────────────────────────────────────

def _score_page(page_no: int, texts: list[dict], tables: list[dict]) -> float:
    """
    Score a single page for DTC content using weighted signals from config.
    Returns score between 0.0 and 1.0.
    All keywords and weights come from config — no magic strings here.
    """
    score      = 0.0
    page_texts = [el for el in texts if el.get("page_pdf") == page_no]
    page_tbls  = [t  for t  in tables if t.get("page_pdf")  == page_no]

    # Collect all text for this page
    all_text = " ".join(el.get("text", "") for el in page_texts)
    upper    = all_text.upper()

    # Signal: breadcrumb contains DTC
    for el in page_texts:
        text  = el.get("text", "")
        upper_el = text.upper()
        if el.get("type") == "section_header" or (el.get("docling_label") == "section_header"):
            for kw in config.DTC_BREADCRUMB_KEYWORDS:
                if kw in upper_el:
                    score += _signal_weight("breadcrumb_dtc")
                    break

    # Signal: heading is DTC heading keyword
    for el in page_texts:
        if el.get("type") == "section_header":
            text = el.get("text", "")
            for kw in config.DTC_HEADING_KEYWORDS:
                if kw.upper() in text.upper():
                    score += _signal_weight("heading_dtc")
                    break

    # Signal: heading IS a DTC code e.g. "P0A0D HV SYSTEM INTERLOCK ERROR"
    for el in page_texts:
        if el.get("type") == "section_header":
            if _DTC_HEAD_RE.match(el.get("text", "").strip()):
                score += _signal_weight("heading_dtc_code")
                break

    # Signal: table header contains CONSULT
    for tbl in page_tbls:
        data = tbl.get("data") or tbl.get("data_raw", [])
        if data:
            header_row = " ".join(data[0]).upper()
            for kw in config.DTC_TABLE_HEADERS:
                if "CONSULT" in kw.upper() and kw.upper() in header_row:
                    score += _signal_weight("table_header_consult")
                    break
            for kw in config.DTC_TABLE_HEADERS:
                if kw.upper() == "DTC" and kw.upper() in header_row:
                    score += _signal_weight("table_header_dtc")
                    break

    # Signal: inline DTC code (weak — many procedure pages reference DTC codes)
    if _DTC_CODE_RE.search(all_text):
        score += _signal_weight("inline_dtc_code")

    return min(score, 1.0)


def _signal_weight(name: str) -> float:
    for signal in config.DTC_SIGNALS:
        if signal["name"] == name:
            return signal["weight"]
    return 0.0


def _classify_page(score: float) -> str:
    """Map score to ownership string."""
    if score >= config.DTC_CONFIDENCE_THRESHOLD:
        return "dtc"
    if score >= config.DTC_CONFIDENCE_THRESHOLD * 0.5:
        return "mixed"
    return "procedure"


# ── Page range builder ────────────────────────────────────────────────────────

def _build_page_ranges(page_classification: dict[int, str], owner: str) -> list[dict]:
    """
    Convert per-page classification map into contiguous page ranges for one owner.
    e.g. {75: dtc, 76: dtc, 77: dtc, 78: procedure} → [{start:75, end:77}]
    """
    pages = sorted(
        pg for pg, cls in page_classification.items()
        if cls == owner or (owner == "dtc_adapter" and cls in ("dtc", "mixed"))
        or (owner == "procedure_adapter" and cls in ("procedure", "mixed"))
    )

    if not pages:
        return []

    ranges = []
    start  = pages[0]
    prev   = pages[0]

    for pg in pages[1:]:
        if pg == prev + 1:
            prev = pg
        else:
            ranges.append({"page_pdf_start": start, "page_pdf_end": prev})
            start = pg
            prev  = pg

    ranges.append({"page_pdf_start": start, "page_pdf_end": prev})
    return ranges


# ── Main splitter ─────────────────────────────────────────────────────────────

def run(
    classified_dir: str | Path = "classified",
    raw_dir:        str | Path = "raw",
) -> bool:
    classified_dir = Path(classified_dir)
    raw_dir        = Path(raw_dir)

    # Load shared profile
    profile_path = raw_dir / "shared_profile.json"
    if not profile_path.exists():
        log.error("shared_profile.json not found in %s", raw_dir)
        return False
    profile = json.loads(profile_path.read_text(encoding="utf-8"))

    # Splitter reads the single classified output file
    batches = list(classified_dir.glob("*_classified.json"))

    if not batches:
        log.error("No classified file found in %s", classified_dir)
        return False

    log.info("Splitting %d classified file(s)", len(batches))

    page_classification: dict[int, str] = {}
    page_scores:         dict[int, float] = {}

    # Score every page across all batches
    for batch_path in batches:
        data   = json.loads(batch_path.read_text(encoding="utf-8"))
        texts  = data.get("text_elements", [])
        tables = data.get("tables", [])
        pm     = data.get("page_map", {})

        batch_updated = False

        for pg_str, info in pm.items():
            pg    = int(pg_str)
            score = _score_page(pg, texts, tables)
            cls   = _classify_page(score)

            page_classification[pg] = cls
            page_scores[pg]         = round(score, 3)

            if info.get("dtc_score") != score or info.get("content_owner") != (
                "dtc_adapter" if cls in ("dtc", "mixed") else "procedure_adapter"
            ):
                info["dtc_score"]    = round(score, 3)
                info["content_owner"] = (
                    "dtc_adapter" if cls in ("dtc", "mixed") else "procedure_adapter"
                )
                batch_updated = True

        if batch_updated:
            # Stamp is_dtc and content_owner on elements
            owner_by_page = {
                pg: ("dtc_adapter" if cls in ("dtc", "mixed") else "procedure_adapter")
                for pg, cls in page_classification.items()
            }

            for el in texts:
                pg    = el.get("page_pdf")
                owner = owner_by_page.get(pg, "procedure_adapter")
                el["is_dtc"]        = owner == "dtc_adapter"
                el["content_owner"] = owner

            for tbl in tables:
                pg    = tbl.get("page_pdf")
                owner = owner_by_page.get(pg, "procedure_adapter")
                tbl["is_dtc"]        = owner == "dtc_adapter"
                tbl["content_owner"] = owner

            for img in data.get("images", []):
                pg    = img.get("page_pdf")
                owner = owner_by_page.get(pg, "procedure_adapter")
                img["content_owner"] = owner

            batch_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

    # Summary
    dtc_pages  = [pg for pg, cls in page_classification.items() if cls in ("dtc", "mixed")]
    proc_pages = [pg for pg, cls in page_classification.items() if cls == "procedure"]
    log.info(
        "Split: %d procedure pages, %d DTC/mixed pages (threshold=%.1f)",
        len(proc_pages), len(dtc_pages), config.DTC_CONFIDENCE_THRESHOLD,
    )

    # Update shared_profile content_split
    cs = profile.setdefault("content_split", {})

    proc = cs.setdefault("procedure_adapter", {})
    proc["page_ranges"] = _build_page_ranges(page_classification, "procedure_adapter")
    proc["status"]      = "completed"

    dtc = cs.setdefault("dtc_adapter", {})
    dtc["page_ranges"] = _build_page_ranges(page_classification, "dtc_adapter")
    dtc["status"]      = "completed" if dtc_pages else "not_required"

    cs["page_classification"] = {str(pg): cls for pg, cls in page_classification.items()}

    profile_path.write_text(
        json.dumps(profile, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("shared_profile.json updated with content_split")
    return True


if __name__ == "__main__":
    run(classified_dir="classified", raw_dir="raw")