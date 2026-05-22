# Odoo Export Tool

Exports operational data from an Odoo 18 instance via XML-RPC into structured files for LLM analysis.

## Setup

1. **Create a virtual environment:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment variables** — create a `.env` file in the project root:
   ```env
   ODOO_URL=https://your-odoo-instance.com
   ODOO_DB=your_database_name
   ODOO_USERNAME=your_username
   ODOO_API_KEY=your_api_key
   ```

## Usage

```bash
python main.py
```

All exports are written to the `Export/` folder.

## Output Structure

| Folder | Contents |
|---|---|
| `Export/repairs/` | One folder per job. Sub-repairs nested under root. Chatter and attachments embedded in `metadata.json`. |
| `Export/knowledge/` | One folder per article containing `body.html` (formatted). Empty, welcome, and date-titled articles are skipped. |
| `Export/helpdesk/` | One folder per ticket with `metadata.json` (includes chatter and attachment list) and any downloaded attachments. |
| `Export/products/` | One JSON file per product template with variants and attributes. |
| `Export/worksheets/` | One subfolder per quality-check record. Fields renamed to human-readable labels. Binary fields saved as images. |
| `Export/sales/` | One folder per sales order with `metadata.json` (includes line items and chatter). |
| `Export/purchases/` | One folder per purchase order with `metadata.json` (includes line items). |
| `Export/documents/` | Documents with metadata and downloaded file content. |

## Notes

- **Incremental exports:** Already-exported records are skipped on subsequent runs.
- **Field discovery:** Custom `x_studio_*` fields are auto-discovered and included where relevant (e.g. repairs).
- **Chatter filtering:** System notifications and empty messages are excluded; only substantive user messages are kept.
- **Signature images:** Inline email signature images (`image001.png`, Outlook attachments) are excluded from downloads.
