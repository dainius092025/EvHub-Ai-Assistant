"""
validate_output.py
==================
Validates adapter output dicts against shared_profile.schema.json.

Called by the adapter pipeline before writing JSON output. If the output
violates the shared envelope schema, errors are logged and reported — the
write still proceeds so the file is available for inspection.

Usage:
    from shared.validate_output import validate_shared_profile

    errors = validate_shared_profile(output_dict)
    if errors:
        for e in errors:
            print(f"  SCHEMA ERROR: {e}")
"""

import json
from pathlib import Path

_SCHEMA_PATH = Path(__file__).parent / "shared_profile.schema.json"
_schema = None


def _load_schema() -> dict:
    global _schema
    if _schema is None:
        with open(_SCHEMA_PATH, encoding="utf-8") as f:
            _schema = json.load(f)
    return _schema


def validate_shared_profile(data: dict) -> list[str]:
    """
    Validate data against shared_profile.schema.json.

    Returns a list of human-readable error strings.
    Empty list means the output is valid.

    Requires jsonschema — if not installed, returns a single warning string
    instead of raising so the pipeline can continue.
    """
    try:
        import jsonschema
    except ImportError:
        return ["jsonschema not installed — skipping validation. Run: pip install jsonschema"]

    schema = _load_schema()
    validator = jsonschema.Draft202012Validator(schema)

    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    return [
        f"{'  >  '.join(str(p) for p in e.path) or '(root)'}:  {e.message}"
        for e in errors
    ]
