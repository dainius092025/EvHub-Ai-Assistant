from pathlib import Path
import hashlib

def compute_document_id(pdf_path: str | Path) -> str:
    """ return stable SHA 256 document id from raw pdf bytes."""
    pdf_path = Path(pdf_path)

    with pdf_path.open("rb") as file:
        pdf_bytes = file.read()
    return hashlib.sha256(pdf_bytes).hexdigest()