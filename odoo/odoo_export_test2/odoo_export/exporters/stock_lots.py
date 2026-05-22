import logging
from .base import BaseExporter
from ..utils import write_json

log = logging.getLogger(__name__)

LOT_FIELDS = [
    "name", "product_id", "product_qty", "ref",
    "expiration_date", "use_date", "note",
    "create_date", "write_date",
]


class StockLotsExporter(BaseExporter):
    """
    Exports stock lots and serial numbers (stock.lot) as a single JSON file.
    """

    def __init__(self, client, adapter, export_dir: str = "odoo_stock_lots_export"):
        super().__init__(client, adapter, export_dir)

    def fetch(self) -> None:
        self.export_dir.mkdir(exist_ok=True)
        out_file = self.export_dir / "lots.json"

        if out_file.exists():
            log.info("Stock lots already exported, skipping.")
            return

        log.info("Fetching Stock Lots / Serial Numbers...")
        fields = self.client.valid_fields("stock.lot", LOT_FIELDS)
        lots = self.client.execute(
            "stock.lot", "search_read",
            domain=[], fields=fields,
        )
        if not lots:
            log.info("No lots found.")
            return

        clean = [self.adapter.adapt_record(l) for l in lots]
        write_json(out_file, clean)
        log.info(f"  -> Saved {len(clean)} lots/serials to lots.json")
        log.info(f"Stock lots export complete → {self.export_dir}")
