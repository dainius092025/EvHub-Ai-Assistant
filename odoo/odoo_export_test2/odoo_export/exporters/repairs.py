import base64
import logging
import re
from collections import defaultdict
from .base import BaseExporter
from ..utils import safe_filename, write_json, clean_chatter, is_signature_image

log = logging.getLogger(__name__)

REPAIR_BASE_FIELDS = [
    "name", "state", "priority", "partner_id", "user_id",
    "tag_ids", "under_warranty", "schedule_date",
    "product_id", "lot_id", "internal_notes",
    "sale_order_id", "repair_request", "ticket_id",
    "picking_type_id", "location_id",
    "create_date", "write_date",
]

_SUB_REPAIR_SUFFIX = re.compile(r"(-\d+)+$")


def _repair_root(name: str) -> str:
    """Strip trailing sub-step suffixes: OF/RO/00001-2-2 → OF/RO/00001."""
    return _SUB_REPAIR_SUFFIX.sub("", name)


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

        fields = self._build_field_list()
        all_repairs = self.client.execute(
            "repair.order", "search_read",
            domain=[], fields=fields,
        )
        if not all_repairs:
            log.info("No repair orders found.")
            return

        # Group by root name
        groups: dict[str, list] = defaultdict(list)
        for r in all_repairs:
            groups[_repair_root(r["name"])].append(r)

        log.info(f"Found {len(all_repairs)} repairs in {len(groups)} jobs.")
        for root_name, group in sorted(groups.items()):
            self._export_group(root_name, group)

        log.info(f"Repair export complete → {self.export_dir}")

    def _build_field_list(self) -> list[str]:
        """Curated base fields + all non-binary x_studio_* custom fields."""
        fields_info = self.client.execute(
            "repair.order", "fields_get", attributes=["string", "type"]
        )
        studio_fields = [
            f for f, meta in fields_info.items()
            if f.startswith("x_studio") and meta.get("type") != "binary"
        ]
        return self.client.valid_fields("repair.order", REPAIR_BASE_FIELDS + studio_fields)

    def _export_group(self, root_name: str, repairs: list) -> None:
        case_dir = self.export_dir / safe_filename(root_name)
        if (case_dir / "metadata.json").exists():
            log.debug(f"  Skipping {root_name} — already exported")
            return
        case_dir.mkdir(exist_ok=True)

        repairs_sorted = sorted(repairs, key=lambda r: r["name"])
        root = repairs_sorted[0]
        sub_repairs = repairs_sorted[1:]

        log.info(f"  Processing {root_name} ({len(repairs)} step(s))")

        clean = self.adapter.adapt_record(root)

        # Root chatter + attachments
        chatter, att_meta = self._fetch_chatter_and_attachments(root["id"], case_dir)
        if chatter:
            clean["chatter"] = chatter
        if att_meta:
            clean["attachments"] = att_meta

        # Sub-repairs
        if sub_repairs:
            subs = []
            for sub in sub_repairs:
                sub_clean = self.adapter.adapt_record(sub)
                sub_chatter, sub_atts = self._fetch_chatter_and_attachments(sub["id"], case_dir)
                if sub_chatter:
                    sub_clean["chatter"] = sub_chatter
                if sub_atts:
                    sub_clean["attachments"] = sub_atts
                subs.append(sub_clean)
            clean["sub_repairs"] = subs

        write_json(case_dir / "metadata.json", clean)

    def _fetch_chatter_and_attachments(self, repair_id: int, case_dir) -> tuple:
        # Attachments
        att_data = self.client.execute(
            "ir.attachment", "search_read",
            domain=[("res_model", "=", "repair.order"), ("res_id", "=", repair_id)],
            fields=["id", "name", "mimetype", "file_size"],
        )
        att_meta = []
        if att_data:
            att_ids = [a["id"] for a in att_data]
            attachments = self.client.execute(
                "ir.attachment", "read",
                ids=att_ids,
                fields=["name", "datas", "mimetype", "file_size"],
            )
            for att in attachments:
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

        # Chatter
        messages = self.client.execute(
            "mail.message", "search_read",
            domain=[("model", "=", "repair.order"), ("res_id", "=", repair_id)],
            fields=["author_id", "date", "body", "message_type", "is_internal", "email_from"],
        )
        return clean_chatter(messages), att_meta
