import base64
import logging
from .base import BaseExporter
from ..utils import safe_filename, write_json, strip_html

log = logging.getLogger(__name__)

TASK_FIELDS = [
    "name", "description", "project_id", "stage_id", "tag_ids",
    "user_ids", "partner_id", "priority", "sequence",
    "create_date", "write_date", "date_deadline", "date_last_stage_update",
    "child_ids", "depend_on_ids",
]


class ProjectTaskExporter(BaseExporter):
    """
    Exports project tasks with description, chatter, and attachments.
    """

    def __init__(self, client, adapter, export_dir: str = "odoo_tasks_export", limit: int = 0):
        super().__init__(client, adapter, export_dir)
        self.limit = limit

    def fetch(self) -> None:
        self.export_dir.mkdir(exist_ok=True)
        log.info("Fetching Project Tasks...")

        kwargs = {"domain": [], "fields": ["id", "name"]}
        if self.limit:
            kwargs["limit"] = self.limit

        records = self.client.execute("project.task", "search_read", **kwargs)
        if not records:
            log.info("No tasks found.")
            return

        task_ids = [r["id"] for r in records]
        log.info(f"Found {len(task_ids)} tasks. Reading full fields...")

        fields = self.client.valid_fields("project.task", TASK_FIELDS)
        tasks = self.client.execute("project.task", "read", ids=task_ids, fields=fields)
        for task in tasks:
            self._export_task(task)

        log.info(f"Tasks export complete → {self.export_dir}")

    def _export_task(self, task: dict) -> None:
        task_id = task["id"]
        task_name = task.get("name") or f"Task_{task_id}"
        case_dir = self.export_dir / safe_filename(f"{task_id}_{task_name}")
        case_dir.mkdir(exist_ok=True)

        description_html = task.get("description") or ""
        description_text = strip_html(description_html)

        # Attachments
        att_data = self.client.execute(
            "ir.attachment", "search_read",
            domain=[("res_model", "=", "project.task"), ("res_id", "=", task_id)],
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
                attachment_meta.append({"name": file_name, "mimetype": att.get("mimetype"), "size": att.get("file_size")})
                raw = att.get("datas")
                if raw:
                    try:
                        (case_dir / file_name).write_bytes(base64.b64decode(raw))
                    except Exception as e:
                        log.warning(f"Could not save {file_name}: {e}")

        # Chatter
        messages = self.client.execute(
            "mail.message", "search_read",
            domain=[("model", "=", "project.task"), ("res_id", "=", task_id)],
            fields=["author_id", "date", "body", "message_type", "subtype_id", "is_internal"],
        )
        if messages:
            clean_messages = [{
                **self.adapter.adapt_record(m),
                "body_text": strip_html(m.get("body") or ""),
            } for m in messages]
            write_json(case_dir / "chatter.json", clean_messages)

        task["_attachments"] = attachment_meta
        task["description_text"] = description_text
        clean_task = self.adapter.adapt_record({k: v for k, v in task.items() if k != "description"})
        write_json(case_dir / "metadata.json", clean_task)
        log.info(f"  -> {task_name} (ID: {task_id})")
