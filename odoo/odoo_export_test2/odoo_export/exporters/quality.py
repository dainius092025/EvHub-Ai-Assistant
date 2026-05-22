import logging
from .base import BaseExporter
from ..utils import safe_filename, write_json, strip_html

log = logging.getLogger(__name__)

CHECK_FIELDS = [
    "name", "product_id", "lot_id", "point_id",
    "production_id", "workcenter_id", "workorder_id", "picking_id",
    "result", "failure_message", "note",
    "create_date", "write_date", "state",
]

ALERT_FIELDS = [
    "name", "description", "stage_id", "team_id",
    "reason_id", "tag_ids", "product_id", "lot_id",
    "workcenter_id", "create_date", "date_close",
]

POINT_FIELDS = [
    "name", "title", "product_id", "product_category_id",
    "picking_type_id", "operation_id", "workcenter_id",
    "measure_on", "point_type", "team_id",
    "tolerance", "norm", "note",
    "create_date", "write_date",
]


class QualityExporter(BaseExporter):
    """
    Exports quality checks, quality alerts, and quality control points with chatter.
    """

    def __init__(self, client, adapter, export_dir: str = "odoo_quality_export"):
        super().__init__(client, adapter, export_dir)

    def fetch(self) -> None:
        self.export_dir.mkdir(exist_ok=True)
        self._fetch_checks()
        self._fetch_alerts()
        self._fetch_points()
        log.info(f"Quality export complete → {self.export_dir}")

    def _fetch_checks(self) -> None:
        log.info("Fetching Quality Checks...")
        check_fields = self.client.valid_fields("quality.check", CHECK_FIELDS)
        checks = self.client.execute(
            "quality.check", "search_read",
            domain=[], fields=check_fields,
        )
        if not checks:
            log.info("No quality checks found.")
            return

        log.info(f"Found {len(checks)} quality checks.")
        checks_dir = self.export_dir / "checks"
        checks_dir.mkdir(exist_ok=True)

        for check in checks:
            check_id = check["id"]
            name = check.get("name") or f"Check_{check_id}"
            note_text = strip_html(check.get("note") or "")
            failure_text = strip_html(check.get("failure_message") or "")

            messages = self.client.execute(
                "mail.message", "search_read",
                domain=[("model", "=", "quality.check"), ("res_id", "=", check_id)],
                fields=["author_id", "date", "body", "message_type"],
            )
            clean_messages = [{
                **self.adapter.adapt_record(m),
                "body_text": strip_html(m.get("body") or ""),
            } for m in messages]

            check_dir = checks_dir / safe_filename(f"{check_id}_{name}")
            if (check_dir / "metadata.json").exists():
                log.debug(f"  Skipping check {name} — already exported")
                continue
            check_dir.mkdir(exist_ok=True)

            clean_check = self.adapter.adapt_record({k: v for k, v in check.items() if k not in ("note", "failure_message")})
            clean_check["note_text"] = note_text
            clean_check["failure_text"] = failure_text
            write_json(check_dir / "metadata.json", clean_check)
            if clean_messages:
                write_json(check_dir / "chatter.json", clean_messages)

        log.info(f"  -> Exported {len(checks)} quality checks")

    def _fetch_alerts(self) -> None:
        log.info("Fetching Quality Alerts...")
        alert_fields = self.client.valid_fields("quality.alert", ALERT_FIELDS)
        alerts = self.client.execute(
            "quality.alert", "search_read",
            domain=[], fields=alert_fields,
        )
        if not alerts:
            log.info("No quality alerts found.")
            return

        log.info(f"Found {len(alerts)} quality alerts.")
        alerts_dir = self.export_dir / "alerts"
        alerts_dir.mkdir(exist_ok=True)

        for alert in alerts:
            alert_id = alert["id"]
            name = alert.get("name") or f"Alert_{alert_id}"
            desc_text = strip_html(alert.get("description") or "")

            messages = self.client.execute(
                "mail.message", "search_read",
                domain=[("model", "=", "quality.alert"), ("res_id", "=", alert_id)],
                fields=["author_id", "date", "body", "message_type"],
            )
            clean_messages = [{
                **self.adapter.adapt_record(m),
                "body_text": strip_html(m.get("body") or ""),
            } for m in messages]

            alert_dir = alerts_dir / safe_filename(f"{alert_id}_{name}")
            if (alert_dir / "metadata.json").exists():
                log.debug(f"  Skipping alert {name} — already exported")
                continue
            alert_dir.mkdir(exist_ok=True)

            clean_alert = self.adapter.adapt_record({k: v for k, v in alert.items() if k != "description"})
            clean_alert["description_text"] = desc_text
            write_json(alert_dir / "metadata.json", clean_alert)
            if clean_messages:
                write_json(alert_dir / "chatter.json", clean_messages)

        log.info(f"  -> Exported {len(alerts)} quality alerts")

    def _fetch_points(self) -> None:
        log.info("Fetching Quality Control Points...")
        out_file = self.export_dir / "control_points.json"
        if out_file.exists():
            log.debug("  Skipping quality control points — already exported")
            return

        point_fields = self.client.valid_fields("quality.point", POINT_FIELDS)
        points = self.client.execute(
            "quality.point", "search_read",
            domain=[], fields=point_fields,
        )
        if not points:
            log.info("No quality control points found.")
            return

        clean = [self.adapter.adapt_record(p) for p in points]
        write_json(out_file, clean)
        log.info(f"  -> Exported {len(clean)} quality control points")
