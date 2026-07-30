import base64
import logging
import re
from collections import defaultdict
from .base import BaseExporter
from ..utils import safe_filename, write_json, clean_chatter, is_signature_image

log = logging.getLogger(__name__)

REPAIR_BASE_FIELDS = [
    "name", "state", "internal_notes",
    "create_date", "write_date",
]

# Legacy/duplicate x_studio fields that are never populated — excluded from fetch.
_X_STUDIO_EXCLUDE = {
    "x_studio_brand",                         # duplicate of x_studio_many2one_field_d3_1iffi7qk6
    "x_studio_customer_complaint",            # duplicate of x_studio_customer_complaint_1
    "x_studio_model_1",                       # duplicate of x_studio_model
    "x_studio_model_2",                       # duplicate of x_studio_model
    "x_studio_many2one_field_630_1jaditor2",  # abandoned test field
    "x_studio_selection_field_246_1if5vftoc", # abandoned test field
}

# Auto-generated Studio field names (contain _field_<hash>) get renamed using
# their human-readable string label from fields_get. Human-named fields
# (e.g. x_studio_reg_number) just have the x_studio_ prefix stripped.
_CRYPTIC_NAME_RE = re.compile(r"^x_studio_\w+_field_\w+")
_TRAILING_COUNTER_RE = re.compile(r"_\d+$")

_SUB_REPAIR_SUFFIX = re.compile(r"(-\d+)+$")


def _repair_root(name: str) -> str:
    """Strip trailing sub-step suffixes: OF/RO/00001-2-2 → OF/RO/00001."""
    return _SUB_REPAIR_SUFFIX.sub("", name)


def _label_to_snake(label: str) -> str:
    snake = re.sub(r"\s+", "_", label.strip().lower())
    return re.sub(r"[^\w]", "", snake)


class RepairOrderExporter(BaseExporter):
    """
    Exports repair orders grouped by root job.
    Sub-repairs (OF/RO/00001-2, -2-2 …) are nested under the root record.
    Chatter and attachments are embedded in metadata.json.
    """

    def __init__(self, client, adapter, export_dir: str | Path = "odoo_repairs_export"):
        super().__init__(client, adapter, export_dir)

    def fetch(self) -> None:
        self.export_dir.mkdir(exist_ok=True)
        log.info("Fetching Repair Orders...")

        fields, rename_map = self._build_field_list()
        all_repairs = self.client.execute(
            "repair.order", "search_read",
            domain=[], fields=fields,
        )
        if not all_repairs:
            log.info("No repair orders found.")
            return

        groups: dict[str, list] = defaultdict(list)
        for r in all_repairs:
            groups[_repair_root(r["name"])].append(r)

        log.info(f"Found {len(all_repairs)} repairs in {len(groups)} jobs.")
        for root_name, group in sorted(groups.items()):
            self._export_group(root_name, group, rename_map)

        log.info(f"Repair export complete → {self.export_dir}")

    def _build_field_list(self) -> tuple[list[str], dict[str, str]]:
        """
        Returns (field_list, rename_map).
        field_list: curated base fields + active non-binary x_studio_* fields.
        rename_map: every x_studio key → clean snake_case name for output.

        Rename strategy:
        - Cryptic auto-generated names (x_studio_*_field_<hash>): use the
          human-readable string label from fields_get.
        - _filename companion fields: derive from parent label + "_filename".
        - Human-named fields (x_studio_reg_number etc.): strip the x_studio_
          prefix and any trailing _1/_2 counter suffixes.
        """
        fields_info = self.client.execute(
            "repair.order", "fields_get", attributes=["string", "type"]
        )

        # First pass: labels for cryptic non-filename fields, used to derive
        # _filename companion names in the second pass.
        cryptic_labels: dict[str, str] = {}
        for f, meta in fields_info.items():
            if _CRYPTIC_NAME_RE.match(f) and not f.endswith("_filename"):
                label = meta.get("string", "")
                if label:
                    cryptic_labels[f] = _label_to_snake(label)

        studio_fields = []
        rename_map: dict[str, str] = {}
        for f, meta in fields_info.items():
            if not f.startswith("x_studio"):
                continue
            if meta.get("type") == "binary" or f in _X_STUDIO_EXCLUDE:
                continue
            studio_fields.append(f)

            if _CRYPTIC_NAME_RE.match(f):
                if f.endswith("_filename"):
                    parent = f[: -len("_filename")]
                    parent_label = cryptic_labels.get(parent, "")
                    rename_map[f] = (parent_label + "_filename") if parent_label else f
                else:
                    rename_map[f] = cryptic_labels.get(f, f)
            else:
                # Strip x_studio_ prefix; remove trailing _1/_2 counters left
                # by Studio when fields are renamed or recreated.
                clean = _TRAILING_COUNTER_RE.sub("", f[len("x_studio_"):])
                rename_map[f] = clean

        validated = self.client.valid_fields("repair.order", REPAIR_BASE_FIELDS + studio_fields)
        return validated, rename_map

    def _apply_rename(self, record: dict, rename_map: dict[str, str]) -> dict:
        if not rename_map:
            return record
        return {rename_map.get(k, k): v for k, v in record.items()}

    def _export_group(self, root_name: str, repairs: list, rename_map: dict) -> None:
        case_dir = self.export_dir / safe_filename(root_name)
        if (case_dir / "metadata.json").exists():
            log.debug(f"  Skipping {root_name} — already exported")
            return
        case_dir.mkdir(exist_ok=True)

        repairs_sorted = sorted(repairs, key=lambda r: r["name"])
        root = repairs_sorted[0]
        sub_repairs = repairs_sorted[1:]

        log.info(f"  Processing {root_name} ({len(repairs)} step(s))")

        clean = self._apply_rename(self.adapter.adapt_record(root), rename_map)

        chatter, att_meta = self._fetch_chatter_and_attachments(root["id"], case_dir)
        if chatter:
            clean["chatter"] = chatter
        if att_meta:
            clean["attachments"] = att_meta

        if sub_repairs:
            subs = []
            for sub in sub_repairs:
                sub_clean = self._apply_rename(self.adapter.adapt_record(sub), rename_map)
                sub_chatter, sub_atts = self._fetch_chatter_and_attachments(sub["id"], case_dir)
                if sub_chatter:
                    sub_clean["chatter"] = sub_chatter
                if sub_atts:
                    sub_clean["attachments"] = sub_atts
                subs.append(sub_clean)
            clean["sub_repairs"] = subs

        write_json(case_dir / "metadata.json", clean)

    def _fetch_chatter_and_attachments(self, repair_id: int, case_dir) -> tuple:
        att_data = self.client.execute(
            "ir.attachment", "search_read",
            domain=[("res_model", "=", "repair.order"), ("res_id", "=", repair_id)],
            fields=["name", "datas", "mimetype", "file_size"],
        )
        att_meta = []
        for att in att_data:
            file_name = safe_filename(att["name"])
            if is_signature_image(file_name, att.get("mimetype"), att.get("file_size")):
                continue
            att_meta.append({"name": file_name, "mimetype": att.get("mimetype"), "size": att.get("file_size")})
            raw = att.get("datas")
            if raw:
                try:
                    (case_dir / file_name).write_bytes(base64.b64decode(raw))
                except Exception as e:
                    log.warning(f"    Could not save {file_name}: {e}")

        messages = self.client.execute(
            "mail.message", "search_read",
            domain=[("model", "=", "repair.order"), ("res_id", "=", repair_id)],
            fields=["author_id", "date", "body", "message_type", "is_internal", "email_from"],
        )
        return clean_chatter(messages), att_meta
