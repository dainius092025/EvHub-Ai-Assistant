import base64
import logging
from .base import BaseExporter
from ..utils import write_json, safe_filename

log = logging.getLogger(__name__)

WORKSHEET_PREFIX = "x_quality_check_worksheet_template"

SKIP_FIELDS = {
    "__last_update", "display_name",
    "create_uid", "write_uid",
}


class WorksheetExporter(BaseExporter):
    """
    Dynamically discovers and exports all custom quality-check worksheet
    template models (x_quality_check_worksheet_template_*).
    Each QC record gets its own subfolder: <ModelLabel>/<QC-ref>/data.json + images.
    """

    def __init__(self, client, adapter, export_dir: str | Path = "odoo_worksheets_export"):
        super().__init__(client, adapter, export_dir)

    def fetch(self) -> None:
        self.export_dir.mkdir(exist_ok=True)

        all_models = self.client.execute(
            "ir.model", "search_read",
            domain=[("model", "like", WORKSHEET_PREFIX)],
            fields=["model", "name"],
        )
        if not all_models:
            log.info("No worksheet template models found.")
            return

        log.info(f"Found {len(all_models)} worksheet template models.")

        for m in all_models:
            model_name = m["model"]
            label = m["name"]
            model_dir = self.export_dir / safe_filename(label)

            log.info(f"  Fetching {label} ({model_name})...")
            try:
                fields_info = self.client.execute(
                    model_name, "fields_get", attributes=["string", "type"]
                )
                text_fields, binary_fields = self._split_fields(model_name, fields_info)

                records = self.client.execute(
                    model_name, "search_read",
                    domain=[], fields=text_fields,
                )
                log.info(f"    -> {len(records)} records")

                for record in records:
                    self._export_record(model_name, record, fields_info, binary_fields, model_dir)

            except Exception as e:
                log.error(f"  Failed to export {model_name}: {e}")

        log.info(f"Worksheet export complete → {self.export_dir}")

    def _split_fields(self, model: str, fields_info: dict) -> tuple[list, list]:
        text_fields = []
        binary_fields = []
        for f, meta in fields_info.items():
            if f in SKIP_FIELDS:
                continue
            if meta.get("type") == "binary":
                binary_fields.append(f)
            else:
                text_fields.append(f)
        text_fields = self.client._probe_fields(model, text_fields)
        return text_fields, binary_fields

    def _export_record(self, model_name: str, record: dict, fields_info: dict, binary_fields: list, model_dir) -> None:
        record_id = record.get("id")
        # Use x_name or id as the folder name
        ref = record.get("x_name") or record.get("name") or str(record_id)
        record_dir = model_dir / safe_filename(str(ref))

        if (record_dir / "data.json").exists():
            log.debug(f"    Skipping record {ref} — already exported")
            return

        record_dir.mkdir(parents=True, exist_ok=True)

        # Rename cryptic field keys to human-readable labels, then clean
        relabeled = {fields_info.get(k, {}).get("string") or k: v for k, v in record.items()}
        clean = self.adapter.adapt_record(relabeled)

        write_json(record_dir / "data.json", clean)

        # Download binary (image) fields
        if binary_fields:
            try:
                bin_record = self.client.execute(
                    model_name, "read",
                    ids=[record_id],
                    fields=binary_fields,
                )
                if bin_record:
                    for field_name in binary_fields:
                        raw = bin_record[0].get(field_name)
                        if not raw:
                            continue
                        field_label = fields_info.get(field_name, {}).get("string") or field_name
                        file_name = safe_filename(field_label) + ".png"
                        try:
                            (record_dir / file_name).write_bytes(base64.b64decode(raw))
                            log.debug(f"      -> Saved image: {file_name}")
                        except Exception as e:
                            log.warning(f"      -> Could not save {file_name}: {e}")
            except Exception as e:
                log.warning(f"      -> Failed to fetch binary fields for record {record_id}: {e}")
