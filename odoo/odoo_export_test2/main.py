import logging
from pathlib import Path
from config import setup_logging, load_config
from odoo_export.client import OdooClient
from odoo_export.adapter import RecordAdapter
from odoo_export.exporters.repairs import RepairOrderExporter
from odoo_export.exporters.knowledge import KnowledgeBaseExporter
from odoo_export.exporters.helpdesk import HelpdeskExporter
# from odoo_export.exporters.projects import ProjectTaskExporter
# from odoo_export.exporters.manufacturing import ManufacturingExporter
from odoo_export.exporters.products import ProductExporter
from odoo_export.exporters.worksheets import WorksheetExporter
from odoo_export.exporters.sales import SalesExporter
from odoo_export.exporters.documents import DocumentsExporter
from odoo_export.exporters.purchases import PurchasesExporter

log = logging.getLogger(__name__)

EXPORT_ROOT = Path(__file__).parent / "Export"

EXPORTERS = [
    ("Repair Orders",    lambda c, a: RepairOrderExporter(c, a,  EXPORT_ROOT / "repairs")),
    ("Knowledge Base",   lambda c, a: KnowledgeBaseExporter(c, a, EXPORT_ROOT / "knowledge")),
    ("Helpdesk Tickets", lambda c, a: HelpdeskExporter(c, a,      EXPORT_ROOT / "helpdesk")),
    # ("Project Tasks",  lambda c, a: ProjectTaskExporter(c, a,   EXPORT_ROOT / "projects")),
    # ("Quality",        lambda c, a: QualityExporter(c, a,       EXPORT_ROOT / "quality")),
    # ("Manufacturing",  lambda c, a: ManufacturingExporter(c, a, EXPORT_ROOT / "manufacturing")),
    ("Products",         lambda c, a: ProductExporter(c, a,       EXPORT_ROOT / "products")),
    ("Worksheets",       lambda c, a: WorksheetExporter(c, a,     EXPORT_ROOT / "worksheets")),
    # ("Custom Models",  lambda c, a: CustomModelsExporter(c, a,  EXPORT_ROOT / "custom_models")),
    # ("Contacts",       lambda c, a: ContactsExporter(c, a,      EXPORT_ROOT / "contacts")),
    ("Sales Orders",     lambda c, a: SalesExporter(c, a,         EXPORT_ROOT / "sales")),
    # ("Stock Lots",     lambda c, a: StockLotsExporter(c, a,     EXPORT_ROOT / "stock_lots")),
    ("Documents",        lambda c, a: DocumentsExporter(c, a,     EXPORT_ROOT / "documents")),
    ("Purchase Orders",  lambda c, a: PurchasesExporter(c, a,     EXPORT_ROOT / "purchases")),
]


def main():
    setup_logging()

    try:
        config = load_config()
    except EnvironmentError as e:
        log.error(e)
        return

    client = OdooClient(config["url"], config["db"], config["username"], config["api_key"])
    adapter = RecordAdapter()

    try:
        client.verify_connection()
    except Exception as e:
        log.error(f"Failed to connect to Odoo: {e}")
        return

    for label, factory in EXPORTERS:
        try:
            factory(client, adapter).fetch()
        except Exception as e:
            log.error(f"{label} export failed: {e}")

    log.info("All exports complete.")


if __name__ == "__main__":
    main()
