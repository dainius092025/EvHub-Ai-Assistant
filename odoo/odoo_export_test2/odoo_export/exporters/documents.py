import base64
import logging
from .base import BaseExporter
from ..utils import safe_filename, write_json

log = logging.getLogger(__name__)

DOCUMENT_FIELDS = [
    "name", "description", "partner_id", "tag_ids",
    "folder_id", "owner_id", "type", "url",
    "mimetype", "file_size", "active",
    "res_model", "res_id", "attachment_id",
    "create_date", "write_date",
]


class DocumentsExporter(BaseExporter):
    """
    Exports Odoo Documents (documents.document) — metadata and file content.
    Each document gets its own folder containing metadata.json and the file.
    """

    def __init__(self, client, adapter, export_dir: str | Path = "odoo_documents_export"):
        super().__init__(client, adapter, export_dir)

    def fetch(self) -> None:
        self.export_dir.mkdir(exist_ok=True)
        log.info("Fetching Documents...")

        fields = self.client.valid_fields("documents.document", DOCUMENT_FIELDS)
        docs = self.client.execute(
            "documents.document", "search_read",
            domain=[("active", "=", True)], fields=fields,
        )
        if not docs:
            log.info("No documents found.")
            return

        log.info(f"Found {len(docs)} documents.")
        for doc in docs:
            self._export_doc(doc)

        log.info(f"Documents export complete → {self.export_dir}")

    def _export_doc(self, doc: dict) -> None:
        doc_id = doc["id"]
        name = doc.get("name") or f"Document_{doc_id}"
        case_dir = self.export_dir / safe_filename(f"{doc_id}_{name}")

        if (case_dir / "metadata.json").exists():
            log.debug(f"  Skipping {name} — already exported")
            return
        case_dir.mkdir(exist_ok=True)

        log.info(f"  Processing {name} (ID: {doc_id})")

        # Download binary file via linked ir.attachment
        att_ref = doc.get("attachment_id")
        att_id = att_ref[0] if isinstance(att_ref, (list, tuple)) else None
        if att_id and doc.get("type") != "url":
            try:
                att = self.client.execute(
                    "ir.attachment", "read",
                    ids=[att_id], fields=["name", "datas", "mimetype"],
                )
                if att and att[0].get("datas"):
                    file_name = safe_filename(att[0].get("name") or name)
                    (case_dir / file_name).write_bytes(base64.b64decode(att[0]["datas"]))
                    log.info(f"    -> Downloaded file: {file_name}")
            except Exception as e:
                log.warning(f"    -> Could not download file for {name}: {e}")

        clean = self.adapter.adapt_record(doc)
        write_json(case_dir / "metadata.json", clean)
