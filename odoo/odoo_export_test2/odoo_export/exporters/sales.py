import logging
from .base import BaseExporter
from ..utils import safe_filename, write_json, strip_html, clean_chatter

log = logging.getLogger(__name__)

ORDER_FIELDS = [
    "name", "partner_id", "state", "date_order", "validity_date",
    "user_id", "team_id", "note", "amount_untaxed", "amount_total",
    "invoice_status", "create_date", "write_date",
]

LINE_FIELDS = [
    "product_id", "name", "product_uom_qty", "qty_delivered",
    "qty_invoiced", "price_unit", "price_subtotal", "product_uom",
]


class SalesExporter(BaseExporter):
    """
    Exports sale orders with line items and chatter.
    """

    def __init__(self, client, adapter, export_dir: str | Path = "odoo_sales_export"):
        super().__init__(client, adapter, export_dir)

    def fetch(self) -> None:
        self.export_dir.mkdir(exist_ok=True)
        log.info("Fetching Sales Orders...")

        fields = self.client.valid_fields("sale.order", ORDER_FIELDS)
        orders = self.client.execute(
            "sale.order", "search_read",
            domain=[], fields=fields,
        )
        if not orders:
            log.info("No sales orders found.")
            return

        log.info(f"Found {len(orders)} sales orders.")
        for order in orders:
            self._export_order(order)

        log.info(f"Sales export complete → {self.export_dir}")

    def _export_order(self, order: dict) -> None:
        order_id = order["id"]
        name = order.get("name") or f"SO_{order_id}"
        case_dir = self.export_dir / safe_filename(name)

        if (case_dir / "metadata.json").exists():
            log.debug(f"  Skipping {name} — already exported")
            return
        case_dir.mkdir(exist_ok=True)

        log.info(f"  Processing {name} (ID: {order_id})")

        # Line items
        line_fields = self.client.valid_fields("sale.order.line", LINE_FIELDS)
        lines = self.client.execute(
            "sale.order.line", "search_read",
            domain=[("order_id", "=", order_id)], fields=line_fields,
        )

        # Chatter
        messages = self.client.execute(
            "mail.message", "search_read",
            domain=[("model", "=", "sale.order"), ("res_id", "=", order_id)],
            fields=["author_id", "date", "body", "message_type", "is_internal", "email_from"],
        )
        chatter = clean_chatter(messages)

        note_html = order.get("note") or ""
        clean = self.adapter.adapt_record({k: v for k, v in order.items() if k != "note"})
        clean["note_text"] = strip_html(note_html)
        clean["lines"] = [self.adapter.adapt_record(l) for l in lines]
        if chatter:
            clean["chatter"] = chatter
        write_json(case_dir / "metadata.json", clean)
        log.info(f"    -> Saved ({len(lines)} lines, {len(chatter)} messages)")
