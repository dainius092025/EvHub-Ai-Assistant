import re
from datetime import datetime

class RecordAdapter:
    """
    Cleans and standardizes Odoo JSON records.
    """
    
    INTERNAL_FIELDS = {
        "__last_update", "display_name",
        "message_follower_ids", "message_ids", "message_main_attachment_id",
        "message_is_follower", "message_needaction", "message_needaction_counter",
        "message_has_error", "message_has_error_counter", "message_attachment_count",
        "message_partner_ids", "message_has_sms_error", "has_message",
        "website_message_ids", "rating_ids",
        "activity_ids", "activity_state", "activity_user_id", "activity_type_id",
        "activity_type_icon", "activity_date_deadline", "my_activity_date_deadline",
        "activity_summary", "activity_exception_decoration", "activity_exception_icon",
        "activity_calendar_event_id",
        "access_token", "write_uid", "create_uid",
    }

    def adapt_record(self, record: dict) -> dict:
        """Process a single Odoo record, dropping internal and empty fields."""
        if not isinstance(record, dict):
            return record

        clean_record = {}
        for key, value in record.items():
            if key in self.INTERNAL_FIELDS:
                continue

            # Drop nulls and Odoo's "no value" sentinels (False, empty list/string)
            # Keep 0 and 0.0 — they can be meaningful quantities
            if value is None or value is False or value == "" or value == []:
                continue

            # 1. Format Many2one fields [ID, "Name"] → {id, name}
            if isinstance(value, (list, tuple)) and len(value) == 2 and isinstance(value[0], int) and isinstance(value[1], str):
                clean_record[key] = {"id": value[0], "name": value[1]}

            # 2. Standardize date strings
            elif isinstance(value, str):
                clean_record[key] = self._standardize_date(value)

            # 3. Recurse into lists of sub-records
            elif isinstance(value, list):
                items = [self.adapt_record(item) if isinstance(item, dict) else item for item in value]
                if items:
                    clean_record[key] = items

            else:
                clean_record[key] = value

        return clean_record

    def _standardize_date(self, value: str) -> str:
        """
        Convert Odoo date strings to ISO 8601.
        """
        # Match Odoo datetime: YYYY-MM-DD HH:MM:SS
        if re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", value):
            try:
                dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
                return dt.isoformat() + "Z"
            except ValueError:
                pass
        
        # Match Odoo date: YYYY-MM-DD
        if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
            try:
                dt = datetime.strptime(value, "%Y-%m-%d")
                return dt.date().isoformat()
            except ValueError:
                pass
                
        return value
