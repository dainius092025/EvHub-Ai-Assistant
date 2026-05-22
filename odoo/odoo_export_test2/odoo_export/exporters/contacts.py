import logging
from .base import BaseExporter
from ..utils import write_json

log = logging.getLogger(__name__)

PARTNER_FIELDS = [
    "name", "company_name", "email", "phone", "mobile",
    "street", "city", "zip", "country_id", "state_id",
    "is_company", "customer_rank", "supplier_rank",
    "category_id", "industry_id", "comment",
    "create_date", "write_date",
]


class ContactsExporter(BaseExporter):
    """
    Exports res.partner (customers and suppliers) as a single JSON file.
    """

    def __init__(self, client, adapter, export_dir: str = "odoo_contacts_export"):
        super().__init__(client, adapter, export_dir)

    def fetch(self) -> None:
        self.export_dir.mkdir(exist_ok=True)
        out_file = self.export_dir / "contacts.json"

        if out_file.exists():
            log.info("Contacts already exported, skipping.")
            return

        log.info("Fetching Contacts (res.partner)...")
        fields = self.client.valid_fields("res.partner", PARTNER_FIELDS)
        partners = self.client.execute(
            "res.partner", "search_read",
            domain=[],
            fields=fields,
        )
        if not partners:
            log.info("No contacts found.")
            return

        clean = [self.adapter.adapt_record(p) for p in partners]
        write_json(out_file, clean)
        log.info(f"  -> Saved {len(clean)} contacts to contacts.json")
        log.info(f"Contacts export complete → {self.export_dir}")
