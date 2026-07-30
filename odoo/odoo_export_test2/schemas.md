# Export JSON Schemas

All JSON files use UTF-8 encoding with 2-space indentation. Dates are ISO 8601 (UTC, `Z` suffix for datetimes). Fields with empty/false/null values are omitted. `0` and `0.0` are preserved.

---

## Shared Definitions

### Reference Object
Used for Many2One fields throughout all schemas.
```json
{
  "$schema": "https://json-schema.org/draft/2020-12",
  "$id": "reference",
  "type": "object",
  "required": ["id", "name"],
  "properties": {
    "id":   { "type": "integer" },
    "name": { "type": "string" }
  },
  "additionalProperties": false
}
```

### Chatter Message
Used in `chatter` arrays in sales, purchases, helpdesk, and repairs.
```json
{
  "$schema": "https://json-schema.org/draft/2020-12",
  "$id": "chatter_message",
  "type": "object",
  "required": ["author", "date", "type", "body"],
  "properties": {
    "author":   { "type": "string" },
    "date":     { "type": "string", "format": "date-time" },
    "type":     { "type": "string" },
    "body":     { "type": "string" },
    "internal": { "type": "boolean" },
    "from":     { "type": "string" }
  },
  "additionalProperties": false
}
```

### Attachment Metadata
Used in `attachments` arrays in helpdesk and repairs. Describes sibling files in the same subdirectory.
```json
{
  "$schema": "https://json-schema.org/draft/2020-12",
  "$id": "attachment_meta",
  "type": "object",
  "required": ["name", "mimetype", "size"],
  "properties": {
    "name":     { "type": "string" },
    "mimetype": { "type": "string" },
    "size":     { "type": "integer", "minimum": 0 }
  },
  "additionalProperties": false
}
```

---

## 1. Products — `products/products.json`

Single flat array of all `product.template` records.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12",
  "$id": "products",
  "type": "array",
  "items": {
    "type": "object",
    "required": ["id", "name"],
    "properties": {
      "id":                           { "type": "integer" },
      "name":                         { "type": "string" },
      "description_text":             { "type": "string" },
      "description_sale_text":        { "type": "string" },
      "description_picking_text":     { "type": "string" },
      "description_pickingout_text":  { "type": "string" },
      "description_pickingin_text":   { "type": "string" },
      "categ_id":                     { "$ref": "reference" },
      "type":                         { "type": "string" },
      "tag_ids":                      { "type": "array", "items": { "$ref": "reference" } },
      "uom_id":                       { "$ref": "reference" },
      "sale_ok":                      { "type": "boolean" },
      "purchase_ok":                  { "type": "boolean" },
      "active":                       { "type": "boolean" },
      "create_date":                  { "type": "string", "format": "date-time" },
      "write_date":                   { "type": "string", "format": "date-time" }
    }
  }
}
```

---

## 2. Sales — `sales/<order_ref>/metadata.json`

One file per `sale.order`, stored in a subdirectory named after the order reference (e.g. `S00009/`).

```json
{
  "$schema": "https://json-schema.org/draft/2020-12",
  "$id": "sale_order",
  "type": "object",
  "required": ["id", "name"],
  "properties": {
    "id":               { "type": "integer" },
    "name":             { "type": "string" },
    "partner_id":       { "$ref": "reference" },
    "state":            { "type": "string", "enum": ["draft", "sent", "sale", "done", "cancel"] },
    "date_order":       { "type": "string", "format": "date-time" },
    "validity_date":    { "type": "string", "format": "date" },
    "user_id":          { "$ref": "reference" },
    "team_id":          { "$ref": "reference" },
    "note_text":        { "type": "string" },
    "amount_untaxed":   { "type": "number" },
    "amount_total":     { "type": "number" },
    "invoice_status":   { "type": "string", "enum": ["upselling", "invoiced", "to invoice", "no"] },
    "create_date":      { "type": "string", "format": "date-time" },
    "write_date":       { "type": "string", "format": "date-time" },
    "lines": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id"],
        "properties": {
          "id":               { "type": "integer" },
          "product_id":       { "$ref": "reference" },
          "name":             { "type": "string" },
          "product_uom_qty":  { "type": "number" },
          "qty_delivered":    { "type": "number" },
          "qty_invoiced":     { "type": "number" },
          "price_unit":       { "type": "number" },
          "price_subtotal":   { "type": "number" },
          "product_uom":      { "$ref": "reference" }
        }
      }
    },
    "chatter": { "type": "array", "items": { "$ref": "chatter_message" } }
  }
}
```

---

## 3. Purchases — `purchases/<po_ref>/metadata.json`

One file per `purchase.order`, stored in a subdirectory named after the PO reference (e.g. `P00005/`).

```json
{
  "$schema": "https://json-schema.org/draft/2020-12",
  "$id": "purchase_order",
  "type": "object",
  "required": ["id", "name"],
  "properties": {
    "id":               { "type": "integer" },
    "name":             { "type": "string" },
    "partner_id":       { "$ref": "reference" },
    "state":            { "type": "string", "enum": ["draft", "sent", "to approve", "purchase", "done", "cancel"] },
    "date_order":       { "type": "string", "format": "date-time" },
    "date_planned":     { "type": "string", "format": "date-time" },
    "user_id":          { "$ref": "reference" },
    "notes_text":       { "type": "string" },
    "amount_untaxed":   { "type": "number" },
    "amount_total":     { "type": "number" },
    "invoice_status":   { "type": "string" },
    "create_date":      { "type": "string", "format": "date-time" },
    "write_date":       { "type": "string", "format": "date-time" },
    "lines": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id"],
        "properties": {
          "id":             { "type": "integer" },
          "product_id":     { "$ref": "reference" },
          "name":           { "type": "string" },
          "product_qty":    { "type": "number" },
          "qty_received":   { "type": "number" },
          "qty_invoiced":   { "type": "number" },
          "price_unit":     { "type": "number" },
          "price_subtotal": { "type": "number" },
          "product_uom":    { "$ref": "reference" },
          "date_planned":   { "type": "string", "format": "date-time" }
        }
      }
    }
  }
}
```

---

## 4. Helpdesk — `helpdesk/<ticket_ref>/metadata.json`

One file per `helpdesk.ticket`. Signature images are excluded from attachments.

> **Media files:** Attachment files (images, PDFs, etc.) are saved as siblings alongside `metadata.json` in the ticket subdirectory. The `attachments` array in the JSON describes each file.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12",
  "$id": "helpdesk_ticket",
  "type": "object",
  "required": ["id", "name", "stage_id", "priority", "create_date", "write_date", "team_id", "description_text"],
  "properties": {
    "id":               { "type": "integer" },
    "name":             { "type": "string" },
    "description_text": { "type": "string" },
    "stage_id": {
      "type": "object",
      "required": ["id", "name"],
      "properties": {
        "id":   { "type": "integer" },
        "name": { "type": "string" }
      }
    },
    "priority":   { "type": "string" },
    "close_date": { "type": "string", "format": "date-time" },
    "partner_id": {
      "type": "object",
      "required": ["id", "name"],
      "properties": {
        "id":   { "type": "integer" },
        "name": { "type": "string" }
      }
    },
    "team_id": {
      "type": "object",
      "required": ["id", "name"],
      "properties": {
        "id":   { "type": "integer" },
        "name": { "type": "string" }
      }
    },
    "user_id": {
      "type": "object",
      "required": ["id", "name"],
      "properties": {
        "id":   { "type": "integer" },
        "name": { "type": "string" }
      }
    },
    "tag_ids": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "name"],
        "properties": {
          "id":   { "type": "integer" },
          "name": { "type": "string" }
        }
      }
    },
    "create_date": { "type": "string", "format": "date-time" },
    "write_date":  { "type": "string", "format": "date-time" },
    
    "attachments": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "mimetype", "size"],
        "properties": {
          "name":     { "type": "string" },
          "mimetype": { "type": "string" },
          "size":     { "type": "integer", "minimum": 0 }
        }
      }
    },
    "chatter": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["author", "date", "type", "body"],
        "properties": {
          "author":   { "type": "string" },
          "date":     { "type": "string", "format": "date-time" },
          "type":     { "type": "string" },
          "body":     { "type": "string" },
          "internal": { "type": "boolean" },
          "from":     { "type": "string" }
        }
      }
    }
  }
}
```

---

## 5. Documents — `documents/<doc_id>_<doc_name>/metadata.json`

One file per `documents.document`.

> **Media files:** The actual document file (image, PDF, Office file, etc.) is saved as a sibling alongside `metadata.json` in the document subdirectory, using the original filename.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12",
  "$id": "document",
  "type": "object",
  "required": ["id", "name"],
  "properties": {
    "id":            { "type": "integer" },
    "name":          { "type": "string" },
    "description":   { "type": "string" },
    "partner_id":    { "$ref": "reference" },
    "tag_ids":       { "type": "array", "items": { "$ref": "reference" } },
    "folder_id":     { "$ref": "reference" },
    "owner_id":      { "$ref": "reference" },
    "type":          { "type": "string", "enum": ["file", "url"] },
    "url":           { "type": "string" },
    "mimetype":      { "type": "string" },
    "file_size":     { "type": "integer", "minimum": 0 },
    "active":        { "type": "boolean" },
    "res_model":     { "type": "string" },
    "res_id":        { "type": "integer" },
    "attachment_id": { "$ref": "reference" },
    "create_date":   { "type": "string", "format": "date-time" },
    "write_date":    { "type": "string", "format": "date-time" }
  }
}
```

---

## 6. Knowledge Base — `knowledge/<article_id>_<title>/`

Each article has its own subdirectory. Articles are filtered during export to exclude welcome pages, date-titled entries, and empty articles.

### Files per article

| File | Description |
|------|-------------|
| `body.html` | Raw HTML exported from Odoo's rich-text editor. Source of truth; produced by the main export. |
| `body.md` | Cleaned Markdown version with a YAML frontmatter block. Produced by `process_knowledge.py`. |
| `images/<n>_<name>.<ext>` | Images extracted from `body.html`, downloaded from `https://evhub.odoo.com` or decoded from base64. Present only after running `process_knowledge.py` without `--no-images`. |

Run `process_knowledge.py` after the main export to generate `body.md` and download images:

```bash
python odoo_export_test2/process_knowledge.py           # full run (downloads images)
python odoo_export_test2/process_knowledge.py --no-images   # Markdown only, skip downloads
python odoo_export_test2/process_knowledge.py --overwrite   # re-process existing files
python odoo_export_test2/process_knowledge.py --min-words N # change short-article threshold (default 50)
```

### `body.md` frontmatter

```yaml
---
title: <article title from <h1>>
article_id: <integer>
folder: <subdirectory name>
source: evhub_knowledge_base
processed_date: <ISO 8601 date>
word_count: <integer>
image_count: <integer, total <img> tags in body.html>
---
```

### Processing notes

- Odoo `data-*` tracking attributes are stripped before conversion.
- Empty paragraphs and zero-width/non-breaking whitespace are removed.
- `<span data-embedded="file">` elements (embedded Odoo file links) are replaced with `[Attachment: <filename>]` plain-text references.
- Image `src` values are rewritten to relative `images/<n>_<name>.<ext>` paths after download. If a download fails, the full Odoo URL (including the embedded `access_token` query parameter) is kept as a fallback.
- Articles with fewer than 50 words of Markdown content are skipped (no `body.md` is written).

---

## 7. Repairs — `repairs/<ro_ref>/metadata.json`

One file per `repair.order`. Sub-repairs (e.g. `OF/RO/00001-2`) are nested under their root job rather than having their own subdirectory.

> **Media files:** Attachment files (images, PDFs, etc.) are saved as siblings alongside `metadata.json` in the repair order subdirectory. The `attachments` array in the JSON describes each file.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12",
  "$id": "repair_order",
  "type": "object",
  "required": ["id", "name", "state", "create_date", "write_date"],
  "properties": {
    "id":                           { "type": "integer" },
    "name":                         { "type": "string" },
    "state":                        { "type": "string", "enum": ["draft", "confirmed", "under_repair", "ready", "done", "cancel"] },
    "internal_notes":               { "type": "string" },
    "create_date":                  { "type": "string", "format": "date-time" },
    "write_date":                   { "type": "string", "format": "date-time" },
    
    **x_studio fields in more readable formats**
    "reg_number":                   { "type": "string" },
    "mileage_km":                   { "type": "string" },
    "brand": {
      "type": "object",
      "required": ["id", "name"],
      "properties": {
        "id":   { "type": "integer" },
        "name": { "type": "string" }
      }
    },
    "model": {
      "type": "object",
      "required": ["id", "name"],
      "properties": {
        "id":   { "type": "integer" },
        "name": { "type": "string" }
      }
    },
    "arrived":                      { "type": "string", "format": "date-time" },
    "customer_complaint":           { "type": "string" },
    "diagnostic_report_filename":   { "type": "string" },
    "attachments": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "mimetype", "size"],
        "properties": {
          "name":     { "type": "string" },
          "mimetype": { "type": "string" },
          "size":     { "type": "integer", "minimum": 0 }
        }
      }
    },
    "chatter": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["author", "date", "type", "body"],
        "properties": {
          "author":   { "type": "string" },
          "date":     { "type": "string", "format": "date-time" },
          "type":     { "type": "string" },
          "body":     { "type": "string" },
          "internal": { "type": "boolean" },
          "from":     { "type": "string" }
        }
      }
    },
    "sub_repairs": { "type": "array", "items": { "$ref": "repair_order" } }
  },
  "description": "Active x_studio_* fields are included dynamically; binary and legacy duplicate fields are excluded. Cryptic auto-generated Studio keys are renamed to their human-readable snake_case labels."
}
```

---

## 8. Worksheets — `worksheets/<model_label>/<qc_ref>/data.json`

One file per worksheet record, grouped by template model label (e.g. `Disassembly_Checks/`) and then by QC reference (e.g. `QC00159/`).

> **Media files:** Binary fields (images captured during the QC process) are saved as sibling `.png` files alongside `data.json`, named after the field label (e.g. `Mätbild_1.png`). These fields are omitted from the JSON.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12",
  "$id": "worksheet",
  "type": "object",
  "description": "Keys are human-readable field labels derived from x_quality_check_worksheet_template_* models. All text-type fields are included; binary fields are saved as separate .png files.",
  "additionalProperties": {
    "oneOf": [
      { "type": "string" },
      { "type": "number" },
      { "type": "boolean" },
      { "$ref": "reference" }
    ]
  }
}
```
