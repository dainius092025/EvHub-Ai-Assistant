import logging
from .base import BaseExporter
from ..utils import safe_filename, write_json, strip_html

log = logging.getLogger(__name__)

PRODUCTION_FIELDS = [
    "name", "product_id", "product_qty", "bom_id", "state", "origin",
    "date_start", "date_finished", "scheduled_date",
    "workorder_ids", "lot_producing_id", "product_uom_id",
]

WORKORDER_FIELDS = [
    "name", "production_id", "workcenter_id", "state",
    "date_start", "date_finished", "duration", "duration_expected",
    "qty_production", "qty_produced",
]

BOM_FIELDS = [
    "code", "product_tmpl_id", "product_id", "product_qty",
    "product_uom_id", "type", "bom_line_ids",
]

BOM_LINE_FIELDS = [
    "product_id", "product_qty", "product_uom_id",
    "operation_id", "sequence",
]


class ManufacturingExporter(BaseExporter):
    """
    Exports manufacturing orders (with work orders) and bill of materials.
    """

    def __init__(self, client, adapter, export_dir: str = "odoo_manufacturing_export"):
        super().__init__(client, adapter, export_dir)

    def fetch(self) -> None:
        self.export_dir.mkdir(exist_ok=True)
        self._fetch_productions()
        self._fetch_boms()
        log.info(f"Manufacturing export complete → {self.export_dir}")

    def _fetch_productions(self) -> None:
        log.info("Fetching Manufacturing Orders...")
        prod_fields = self.client.valid_fields("mrp.production", PRODUCTION_FIELDS)
        productions = self.client.execute(
            "mrp.production", "search_read",
            domain=[], fields=prod_fields,
        )
        if not productions:
            log.info("No manufacturing orders found.")
            return

        log.info(f"Found {len(productions)} manufacturing orders.")
        prod_dir = self.export_dir / "production_orders"
        prod_dir.mkdir(exist_ok=True)

        for prod in productions:
            prod_id = prod["id"]
            name = prod.get("name") or f"MO_{prod_id}"
            case_dir = prod_dir / safe_filename(name)
            if (case_dir / "metadata.json").exists():
                log.debug(f"  Skipping {name} — already exported")
                continue
            case_dir.mkdir(exist_ok=True)

            # Fetch work orders
            workorder_ids = prod.get("workorder_ids") or []
            workorders = []
            if workorder_ids:
                workorders = self.client.execute(
                    "mrp.workorder", "read",
                    ids=workorder_ids,
                    fields=WORKORDER_FIELDS,
                )

            # Chatter
            messages = self.client.execute(
                "mail.message", "search_read",
                domain=[("model", "=", "mrp.production"), ("res_id", "=", prod_id)],
                fields=["author_id", "date", "body", "message_type"],
            )
            if messages:
                clean_messages = [{
                    **self.adapter.adapt_record(m),
                    "body_text": strip_html(m.get("body") or ""),
                } for m in messages]
                write_json(case_dir / "chatter.json", clean_messages)

            clean_prod = self.adapter.adapt_record(prod)
            clean_prod["work_orders"] = [self.adapter.adapt_record(wo) for wo in workorders]
            write_json(case_dir / "metadata.json", clean_prod)
            log.info(f"  -> {name} ({len(workorders)} work orders)")

    def _fetch_boms(self) -> None:
        log.info("Fetching Bills of Materials...")
        bom_fields = self.client.valid_fields("mrp.bom", BOM_FIELDS)
        boms = self.client.execute(
            "mrp.bom", "search_read",
            domain=[], fields=bom_fields,
        )
        if not boms:
            log.info("No BOMs found.")
            return

        log.info(f"Found {len(boms)} BOMs.")
        bom_dir = self.export_dir / "boms"
        bom_dir.mkdir(exist_ok=True)

        for bom in boms:
            bom_id = bom["id"]
            product = bom.get("product_tmpl_id")
            name = (product[1] if isinstance(product, (list, tuple)) else str(product)) or f"BOM_{bom_id}"
            code = bom.get("code") or ""

            line_ids = bom.get("bom_line_ids") or []
            lines = []
            if line_ids:
                lines = self.client.execute(
                    "mrp.bom.line", "read",
                    ids=line_ids,
                    fields=BOM_LINE_FIELDS,
                )

            clean_bom = self.adapter.adapt_record(bom)
            clean_bom["lines"] = [self.adapter.adapt_record(l) for l in lines]
            fname = safe_filename(f"{bom_id}_{code}_{name}" if code else f"{bom_id}_{name}")
            if (bom_dir / f"{fname}.json").exists():
                log.debug(f"  Skipping BOM {fname} — already exported")
                continue
            write_json(bom_dir / f"{fname}.json", clean_bom)

        log.info(f"  -> Exported {len(boms)} BOMs")
