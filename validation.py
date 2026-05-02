"""
validate.py — sanity check on chunks.json
Run after chunker.py to flag potential issues before handing off to agent team.
"""

from __future__ import annotations
import json, logging
from pathlib import Path

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S", level=logging.INFO)
log = logging.getLogger("validate")


def run(chunks_file: str | Path = "chunks.json") -> None:
    chunks_file = Path(chunks_file)

    if not chunks_file.exists():
        log.error("chunks.json not found — run chunker.py first")
        return

    data   = json.loads(chunks_file.read_text(encoding="utf-8"))
    chunks = data.get("chunks", [])
    log.info("Loaded %d chunks from %s", len(chunks), chunks_file)

    issues = []

    for chunk in chunks:
        cid        = chunk["chunk_id"]
        chunk_type = chunk.get("chunk_type", "procedure")

        # HIGH_VOLTAGE procedure chunk with no prerequisites
        if (chunk_type == "procedure"
                and chunk.get("safety_level") == "HIGH_VOLTAGE"
                and not chunk.get("prerequisites")):
            issues.append({
                "chunk_id":    cid,
                "chunk_type":  chunk_type,
                "issue":       "HIGH_VOLTAGE procedure missing prerequisites",
                "page_manual": chunk.get("page_manual"),
            })

        # Empty chunk
        if (not chunk.get("text_blocks")
                and not chunk.get("tables")
                and not chunk.get("images")):
            issues.append({
                "chunk_id":    cid,
                "chunk_type":  chunk_type,
                "issue":       "Empty chunk — no content",
                "page_manual": chunk.get("page_manual"),
            })

        # Stub chunk — only a section_header, nothing else
        blocks = chunk.get("text_blocks", [])
        if (len(blocks) <= 1
                and not chunk.get("tables")
                and not chunk.get("images")):
            if not blocks or blocks[0].get("type") == "section_header":
                issues.append({
                    "chunk_id":    cid,
                    "chunk_type":  chunk_type,
                    "issue":       "Stub chunk — header only, no content",
                    "page_manual": chunk.get("page_manual"),
                })

    # ── Print summary ──────────────────────────────────────────────────────────
    total       = len(chunks)
    procedures  = sum(1 for c in chunks if c.get("chunk_type") == "procedure") 
    precautions = sum(1 for c in chunks if c.get("chunk_type") == "precaution")
    hv          = sum(1 for c in chunks if c.get("safety_level") == "HIGH_VOLTAGE")
    with_prereq = sum(1 for c in chunks if c.get("prerequisites"))

    log.info("─── Summary ───────────────────────────────")
    log.info("Total chunks:       %d", total)
    log.info("Procedure chunks:   %d", procedures)
    log.info("Precaution chunks:  %d", precautions)
    log.info("HIGH_VOLTAGE:       %d", hv)
    log.info("With prerequisites: %d", with_prereq)
    log.info("Issues found:       %d", len(issues))

    if issues:
        log.warning("─── Issues ────────────────────────────────")
        for issue in issues:
            log.warning("%s  |  %s  |  %s",
                        issue["chunk_id"],
                        issue["page_manual"],
                        issue["issue"])
    else:
        log.info("No issues found")


if __name__ == "__main__":
    run("chunks.json")