import base64
import logging
from .base import BaseExporter
from ..utils import safe_filename, write_json, strip_html, clean_chatter, is_signature_image

log = logging.getLogger(__name__)

TICKET_FIELDS = [
    "name", "description", "tag_ids", "ticket_type_id",
    "stage_id", "priority", "partner_id",
    "create_date", "write_date", "close_date",
    "team_id", "user_id",
]


class HelpdeskExporter(BaseExporter):
    """
    Exports helpdesk tickets with chatter and attachments.
    """

    def __init__(self, client, adapter, export_dir: str | Path = "odoo_helpdesk_export", limit: int = 0):
        super().__init__(client, adapter, export_dir)
        self.limit = limit

    def fetch(self) -> None:
        self.export_dir.mkdir(exist_ok=True)
        log.info("Fetching Helpdesk tickets...")

        kwargs = {"domain": [], "fields": ["id", "name"]}
        if self.limit:
            kwargs["limit"] = self.limit

        records = self.client.execute("helpdesk.ticket", "search_read", **kwargs)
        if not records:
            log.info("No helpdesk tickets found.")
            return

        ticket_ids = [r["id"] for r in records]
        log.info(f"Found {len(ticket_ids)} tickets. Reading full fields...")

        fields = self.client.valid_fields("helpdesk.ticket", TICKET_FIELDS)
        tickets = self.client.execute(
            "helpdesk.ticket", "read",
            ids=ticket_ids,
            fields=fields,
        )

        for ticket in tickets:
            self._export_ticket(ticket)

        log.info(f"Helpdesk export complete → {self.export_dir}")

    def _export_ticket(self, ticket: dict) -> None:
        ticket_id = ticket["id"]
        ticket_name = ticket.get("name") or f"Ticket_{ticket_id}"
        case_dir = self.export_dir / safe_filename(ticket_name)
        if (case_dir / "metadata.json").exists():
            log.debug(f"  Skipping {ticket_name} — already exported")
            return
        case_dir.mkdir(exist_ok=True)

        log.info(f"  Processing {ticket_name} (ID: {ticket_id})")

        # Strip HTML description
        description_html = ticket.get("description") or ""
        description_text = strip_html(description_html)

        # Attachments
        att_data = self.client.execute(
            "ir.attachment", "search_read",
            domain=[("res_model", "=", "helpdesk.ticket"), ("res_id", "=", ticket_id)],
            fields=["id", "name", "mimetype", "file_size"],
        )
        attachment_meta = []
        if att_data:
            att_ids = [a["id"] for a in att_data]
            attachments = self.client.execute(
                "ir.attachment", "read",
                ids=att_ids,
                fields=["name", "datas", "mimetype", "file_size"],
            )
            for att in attachments:
                file_name = safe_filename(att["name"])
                if is_signature_image(file_name, att.get("mimetype"), att.get("file_size")):
                    log.debug(f"    -> Skipping signature image: {file_name}")
                    continue
                attachment_meta.append({"name": file_name, "mimetype": att.get("mimetype"), "size": att.get("file_size")})
                raw = att.get("datas")
                if raw:
                    try:
                        (case_dir / file_name).write_bytes(base64.b64decode(raw))
                        log.info(f"    -> Saved attachment: {file_name}")
                    except Exception as e:
                        log.warning(f"    -> Could not save {file_name}: {e}")

        # Chatter
        messages = self.client.execute(
            "mail.message", "search_read",
            domain=[("model", "=", "helpdesk.ticket"), ("res_id", "=", ticket_id)],
            fields=["author_id", "date", "body", "message_type", "is_internal", "email_from"],
        )
        chatter = clean_chatter(messages)

        clean_ticket = self.adapter.adapt_record({k: v for k, v in ticket.items() if k != "description"})
        clean_ticket["description_text"] = description_text
        if attachment_meta:
            clean_ticket["attachments"] = attachment_meta
        if chatter:
            clean_ticket["chatter"] = chatter
        write_json(case_dir / "metadata.json", clean_ticket)
        log.info(f"    -> Saved metadata.json ({len(chatter)} messages)")
