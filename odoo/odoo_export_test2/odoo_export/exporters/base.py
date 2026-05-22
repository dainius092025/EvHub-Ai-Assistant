from pathlib import Path
from ..client import OdooClient
from ..adapter import RecordAdapter

class BaseExporter:
    """
    Base class for all Odoo exporters.
    """
    def __init__(self, client: OdooClient, adapter: RecordAdapter, export_dir: str | Path):
        self.client = client
        self.adapter = adapter
        self.export_dir = Path(export_dir)
        self.export_dir.mkdir(parents=True, exist_ok=True)

    def fetch(self) -> None:
        """To be implemented by subclasses."""
        raise NotImplementedError
