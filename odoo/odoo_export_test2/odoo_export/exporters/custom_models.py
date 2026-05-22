import logging
from .base import BaseExporter
from ..utils import write_json

log = logging.getLogger(__name__)

# Small reference / lookup models to dump as flat JSON files.
# Each entry: (odoo_model, output_filename)
REFERENCE_MODELS = [
    ("x_manufacturer",           "manufacturers.json"),
    ("x_model",                  "vehicle_models.json"),
    ("x_warranty_claim_overv",        "warranty_claims.json"),
    ("x_warranty_claim_overv_stage",  "warranty_claim_stages.json"),
    ("x_warranty_database",           "warranty_database.json"),
    ("x_warranty_database_stage",     "warranty_database_stages.json"),
]


class CustomModelsExporter(BaseExporter):
    """
    Exports small custom reference models (manufacturers, vehicle models,
    warranty claims/database) as flat JSON files.
    """

    def __init__(self, client, adapter, export_dir: str = "odoo_custom_export"):
        super().__init__(client, adapter, export_dir)

    def fetch(self) -> None:
        self.export_dir.mkdir(exist_ok=True)

        for model, filename in REFERENCE_MODELS:
            out_file = self.export_dir / filename
            if out_file.exists():
                log.debug(f"  Skipping {model} — already exported")
                continue

            log.info(f"Fetching {model}...")
            try:
                fields_info = self.client.execute(model, "fields_get", attributes=["string"])
                fields = self.client._probe_fields(model, list(fields_info.keys()))
                records = self.client.execute(model, "search_read", domain=[], fields=fields)
                clean = [self.adapter.adapt_record(r) for r in records]
                write_json(out_file, clean)
                log.info(f"  -> {len(clean)} records saved to {filename}")
            except Exception as e:
                log.warning(f"  Skipping {model}: {e}")

        log.info(f"Custom models export complete → {self.export_dir}")
