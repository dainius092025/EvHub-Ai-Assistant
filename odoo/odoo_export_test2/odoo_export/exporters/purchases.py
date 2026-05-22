import logging
from .base import BaseExporter
from ..utils import safe_filename, write_json, strip_html

log = logging.getLogger(__name__)

ORDER_FIELDS = [
    "name", "partner_id", "state", "date_order", "date_planned",
    "user_id", "notes", "amount_untaxed", "amount_total",
    "invoice_status", "create_date", "write_date",
]

LINE_FIELDS = [
    "product_id", "name", "product_qty", "qty_received",
    "qty_invoiced", "price_unit", "price_subtotal",
    "product_uom", "date_planned",
]


class PurchasesExporter(BaseExporter):
    """
    Exports purchase orders with line items as a single metadata.json per PO.
    """

    def __init__(self, client, adapter, export_dir: str | Path = "odoo_purchases_export"):
        super().__init__(client, adapter, export_dir)

    def fetch(self) -> None:
        self.export_dir.mkdir(exist_ok=True)
        log.info("Fetching Purchase Orders...")

        fields = self.client.valid_fields("purchase.order", ORDER_FIELDS)
        orders = self.client.execute(
            "purchase.order", "search_read",
            domain=[], fields=fields,
        )
        if not orders:
            log.info("No purchase orders found.")
            return

        log.info(f"Found {len(orders)} purchase orders.")
        for order in orders:
            self._export_order(order)

        log.info(f"Purchases export complete → {self.export_dir}")

    def _export_order(self, order: dict) -> None:
        order_id = order["id"]
        name = order.get("name") or f"PO_{order_id}"
        case_dir = self.export_dir / safe_filename(name)

        if (case_dir / "metadata.json").exists():
            log.debug(f"  Skipping {name} — already exported")
            return
        case_dir.mkdir(exist_ok=True)

        log.info(f"  Processing {name} (ID: {order_id})")

        line_fields = self.client.valid_fields("purchase.order.line", LINE_FIELDS)
        lines = self.client.execute(
            "purchase.order.line", "search_read",
            domain=[("order_id", "=", order_id)], fields=line_fields,
        )

        notes_html = order.get("notes") or ""
        clean = self.adapter.adapt_record({k: v for k, v in order.items() if k != "notes"})
        clean["notes_text"] = strip_html(notes_html)
        clean["lines"] = [self.adapter.adapt_record(l) for l in lines]
        write_json(case_dir / "metadata.json", clean)
        log.info(f"    -> Saved ({len(lines)} lines)")
