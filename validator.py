"""
validator.py — Stage 4: Schema validation and safety checks
Runs twice: after extractor (validates raw) and after classifier (validates classified).

Responsibilities (only these):
  - Validate each batch JSON against its schema
  - Run safety checks: HV elements without warnings, empty required fields
  - Run completeness checks: pages with no text, tables with zero rows
  - Write validation_report.json
  - Return True only if zero critical failures

Does NOT:
  - Fix problems
  - Modify any source files
  - Make semantic decisions
"""

from __future__ import annotations
import json, logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import jsonschema
    _HAS_JSONSCHEMA = True
except ImportError:
    _HAS_JSONSCHEMA = False
    logging.warning("jsonschema not installed — install with: pip install jsonschema")

import config

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger("validator")

_BATCH_RE = __import__("re").compile(r"^\d+_\d+\.json$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_schema(schema_path: Path) -> dict | None:
    if not schema_path.exists():
        log.error("Schema not found: %s", schema_path)
        return None
    return json.loads(schema_path.read_text(encoding="utf-8"))


# ── Schema validation ─────────────────────────────────────────────────────────

def _validate_schema(data: dict, schema: dict, batch_name: str) -> list[dict]:
    issues = []
    if not _HAS_JSONSCHEMA:
        issues.append({
            "severity": "warning",
            "batch":    batch_name,
            "check":    "schema_validation",
            "message":  "jsonschema not installed — schema validation skipped",
        })
        return issues

    validator = jsonschema.Draft7Validator(schema)
    for error in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
        issues.append({
            "severity": "critical",
            "batch":    batch_name,
            "check":    "schema_validation",
            "message":  f"{' → '.join(str(p) for p in error.path)}: {error.message}",
        })

    return issues


# ── Safety checks ─────────────────────────────────────────────────────────────

def _check_raw_batch(data: dict, batch_name: str) -> list[dict]:
    """Safety and completeness checks on raw batch output."""
    issues = []

    texts  = data.get("text_elements", [])
    tables = data.get("tables", [])
    images = data.get("images", [])
    pm     = data.get("page_map", {})

    # All images must be PNG
    for img in images:
        if img.get("format_saved") != "png":
            issues.append({
                "severity": "critical",
                "batch":    batch_name,
                "check":    "image_format",
                "message":  f"image {img.get('image_id')} format_saved={img.get('format_saved')} not png",
            })

    # All images must have labelled bbox coordinate system
    for img in images:
        if not img.get("bbox_coordinate_system"):
            issues.append({
                "severity": "critical",
                "batch":    batch_name,
                "check":    "bbox_coordinate_system",
                "message":  f"image {img.get('image_id')} missing bbox_coordinate_system",
            })

    # All text elements must have labelled bbox coordinate system
    for el in texts:
        if not el.get("bbox_coordinate_system"):
            issues.append({
                "severity": "warning",
                "batch":    batch_name,
                "check":    "bbox_coordinate_system",
                "message":  f"element {el.get('element_id')} missing bbox_coordinate_system",
            })

    # Tables with zero rows (extraction failure)
    for tbl in tables:
        if tbl.get("num_rows", 0) <= 1 and tbl.get("tableformer_used"):
            issues.append({
                "severity": "warning",
                "batch":    batch_name,
                "check":    "table_empty",
                "message":  f"table {tbl.get('table_id')} has {tbl.get('num_rows')} rows — possible TableFormer failure",
            })

    # Pages with no text at all
    pages_with_text = {el.get("page_pdf") for el in texts}
    for pg_str, info in pm.items():
        pg = int(pg_str)
        if pg not in pages_with_text and not info.get("is_scanned"):
            issues.append({
                "severity": "warning",
                "batch":    batch_name,
                "check":    "page_no_text",
                "message":  f"page {pg} ({info.get('page_manual')}) has no text elements and is not scanned",
            })

    return issues


def _check_classified_batch(data: dict, batch_name: str) -> list[dict]:
    """Safety and completeness checks on classified batch output."""
    issues = []
    texts = data.get("text_elements", [])

    # Every text element must have type and safety_level
    for el in texts:
        if not el.get("type"):
            issues.append({
                "severity": "critical",
                "batch":    batch_name,
                "check":    "missing_type",
                "message":  f"element {el.get('element_id')} missing type",
            })
        if not el.get("safety_level"):
            issues.append({
                "severity": "critical",
                "batch":    batch_name,
                "check":    "missing_safety_level",
                "message":  f"element {el.get('element_id')} missing safety_level",
            })

    # HV elements should have at least one warning nearby on same page
    hv_pages = {
        el.get("page_pdf")
        for el in texts
        if el.get("safety_level") == "HIGH_VOLTAGE" and el.get("type") == "procedure_step"
    }
    warning_pages = {
        el.get("page_pdf")
        for el in texts
        if el.get("type") == "warning"
    }
    for pg in hv_pages:
        if pg not in warning_pages:
            issues.append({
                "severity": "warning",
                "batch":    batch_name,
                "check":    "hv_missing_warning",
                "message":  f"page {pg} has HIGH_VOLTAGE steps but no warning element on same page",
            })

    # Every table must have table_type
    for tbl in data.get("tables", []):
        if not tbl.get("table_type"):
            issues.append({
                "severity": "critical",
                "batch":    batch_name,
                "check":    "missing_table_type",
                "message":  f"table {tbl.get('table_id')} missing table_type",
            })

    # Every image must have subtype
    for img in data.get("images", []):
        if not img.get("subtype"):
            issues.append({
                "severity": "warning",
                "batch":    batch_name,
                "check":    "missing_image_subtype",
                "message":  f"image {img.get('image_id')} missing subtype",
            })

    return issues


# ── Main validation runner ────────────────────────────────────────────────────

def run(
    input_dir:   str | Path,
    stage:       str,          # "raw" or "classified"
    output_dir:  str | Path | None = None,
) -> bool:
    """
    Validate batch files (raw stage) or single classified file (classified stage).
    Writes validation_report_{stage}.json.
    Returns True if zero critical failures.
    """
    input_dir  = Path(input_dir)
    output_dir = Path(output_dir) if output_dir else input_dir

    if stage == "raw":
        schema_path   = config.SCHEMA_RAW_BATCH
        check_fn: Any = _check_raw_batch
        # Raw stage — validate individual batch files
        batches = sorted(
            [f for f in input_dir.glob("*.json") if _BATCH_RE.match(f.name)],
            key=lambda p: int(p.stem.split("_")[0]),
        )
    elif stage == "classified":
        schema_path = config.SCHEMA_CLASSIFIED
        check_fn    = _check_classified_batch
        # Classified stage — validate the single output file
        batches = list(input_dir.glob("*_classified.json"))
    else:
        log.error("stage must be 'raw' or 'classified', got: %s", stage)
        return False

    schema = _load_schema(schema_path)

    if not batches:
        log.error("No files found to validate in %s (stage=%s)", input_dir, stage)
        return False

    log.info("Validating %d %s file(s)", len(batches), stage)

    all_issues: list[dict] = []
    critical_count = 0

    for batch_path in batches:
        try:
            data = json.loads(batch_path.read_text(encoding="utf-8"))
        except Exception as exc:
            all_issues.append({
                "severity": "critical",
                "batch":    batch_path.name,
                "check":    "json_parse",
                "message":  str(exc),
            })
            critical_count += 1
            continue

        batch_issues = []

        # Schema validation
        if schema:
            batch_issues.extend(_validate_schema(data, schema, batch_path.name))

        # Content checks
        batch_issues.extend(check_fn(data, batch_path.name))

        n_critical = sum(1 for i in batch_issues if i["severity"] == "critical")
        n_warning  = sum(1 for i in batch_issues if i["severity"] == "warning")
        critical_count += n_critical

        if batch_issues:
            log.warning("%s: %d critical, %d warnings",
                        batch_path.name, n_critical, n_warning)
        else:
            log.info("%s: OK", batch_path.name)

        all_issues.extend(batch_issues)

    # Write report
    report = {
        "stage":          stage,
        "validated_at":   _now(),
        "input_dir":      str(input_dir),
        "total_batches":  len(batches),
        "total_issues":   len(all_issues),
        "critical_count": critical_count,
        "warning_count":  sum(1 for i in all_issues if i["severity"] == "warning"),
        "passed":         critical_count == 0,
        "issues":         all_issues,
    }

    report_path = output_dir / f"validation_report_{stage}.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    if critical_count == 0:
        log.info("Validation PASSED (%d warnings) → %s", report["warning_count"], report_path)
    else:
        log.error("Validation FAILED (%d critical) → %s", critical_count, report_path)

    return critical_count == 0


if __name__ == "__main__":
    import sys
    stage = sys.argv[1] if len(sys.argv) > 1 else "raw"
    run(input_dir="raw", stage=stage)