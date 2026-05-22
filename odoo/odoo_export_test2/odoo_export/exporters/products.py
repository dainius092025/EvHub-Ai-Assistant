import logging
from .base import BaseExporter
from ..utils import safe_filename, write_json, strip_html

log = logging.getLogger(__name__)

PRODUCT_FIELDS = [
    "name", "description", "description_sale", "description_picking",
    "description_pickingout", "description_pickingin",
    "categ_id", "type", "tag_ids", "uom_id",
    "sale_ok", "purchase_ok", "active",
    "create_date", "write_date",
]


class ProductExporter(BaseExporter):
    """
    Exports product catalog (templates) — useful as parts/component reference for LLM.
    """

    def __init__(self, client, adapter, export_dir: str | Path = "odoo_products_export"):
        super().__init__(client, adapter, export_dir)

    def fetch(self) -> None:
        self.export_dir.mkdir(exist_ok=True)
        if (self.export_dir / "products.json").exists():
            log.info("Products already exported, skipping.")
            return
        log.info("Fetching Products...")

        fields = self.client.valid_fields("product.template", PRODUCT_FIELDS)
        products = self.client.execute(
            "product.template", "search_read",
            domain=[("active", "=", True)],
            fields=fields,
        )
        if not products:
            log.info("No products found.")
            return

        log.info(f"Found {len(products)} products.")
        all_products = []

        for product in products:
            desc_fields = ["description", "description_sale", "description_picking",
                           "description_pickingout", "description_pickingin"]
            clean = self.adapter.adapt_record({k: v for k, v in product.items() if k not in desc_fields})

            for field in desc_fields:
                html = product.get(field) or ""
                clean[f"{field}_text"] = strip_html(html) if html else ""

            all_products.append(clean)

        write_json(self.export_dir / "products.json", all_products)
        log.info(f"  -> Saved {len(all_products)} products to products.json")
        log.info(f"Products export complete → {self.export_dir}")
