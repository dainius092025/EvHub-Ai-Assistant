"""
Extended discovery — all Odoo models grouped by prefix category,
sorted by total records per category, then by record count within each category.

Only models with at least one record are shown.
Status column: ✓ = already exported, ★ = has data but not exported.

Output: discover_output.md

Usage: python discover_full.py
"""
import logging
from collections import defaultdict
from datetime import datetime
from config import setup_logging, load_config
from odoo_export.client import OdooClient

EXPORTED_MODELS = {
    "repair.order",
    "helpdesk.ticket",
    "knowledge.article",
    "project.task",
    "quality.check",
    "quality.alert",
    "quality.point",
    "mrp.production",
    "mrp.workorder",
    "mrp.bom",
    "product.template",
    "res.partner",
    "sale.order",
    "sale.order.line",
    "stock.lot",
    "documents.document",
    "purchase.order",
    "purchase.order.line",
    "x_manufacturer",
    "x_model",
    "x_warranty_claim_overv",
    "x_warranty_claim_overv_stage",
    "x_warranty_database",
    "x_warranty_database_stage",
}

OUTPUT_FILE = "discover_output.md"


def main():
    setup_logging(logging.WARNING)
    config = load_config()
    client = OdooClient(config["url"], config["db"], config["username"], config["api_key"])
    client.verify_connection()

    print("\nFetching model list...")
    all_models = client.execute(
        "ir.model", "search_read",
        domain=[("transient", "=", False)],
        fields=["model", "name"],
    )
    print(f"Found {len(all_models)} non-transient models.")
    print("Fetching record counts — this may take a minute...\n")

    # Collect counts for every model
    rows = []
    for i, m in enumerate(all_models, 1):
        print(f"\r  {i}/{len(all_models)} models checked...", end="", flush=True)
        try:
            count = client.execute(m["model"], "search_count", domain=[])
            if count > 0:
                rows.append((m["model"], m["name"], count))
        except Exception:
            pass  # no access or model not queryable
    print()

    # Group by prefix (first segment before the first dot)
    categories: dict[str, list] = defaultdict(list)
    for model, label, count in rows:
        prefix = model.split(".")[0]
        categories[prefix].append((model, label, count))

    # Sort categories by total records descending
    sorted_categories = sorted(
        categories.items(),
        key=lambda item: sum(c for _, _, c in item[1]),
        reverse=True,
    )

    total_records = sum(c for _, _, c in rows)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = []
    lines.append(f"# Odoo Model Discovery\n")
    lines.append(f"Generated: {generated_at}  ")
    lines.append(f"Total records (across all models with data): **{total_records:,}**  ")
    lines.append(f"Legend: ✓ = exported &nbsp; ★ = has data, not exported\n")
    lines.append("---\n")

    for prefix, models in sorted_categories:
        total = sum(c for _, _, c in models)
        sorted_models = sorted(models, key=lambda x: x[2], reverse=True)

        lines.append(f"## {prefix} — {total:,} records\n")
        lines.append("| Model | Label | Records | Status |")
        lines.append("|-------|-------|--------:|:------:|")

        for model, label, count in sorted_models:
            status = "✓" if model in EXPORTED_MODELS else "★"
            lines.append(f"| `{model}` | {label} | {count:,} | {status} |")

        lines.append("")

    output = "\n".join(lines)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(output)

    print(f"Written to {OUTPUT_FILE}")
    print(f"  {len(sorted_categories)} categories, {len(rows)} models with data, {total_records:,} total records")


if __name__ == "__main__":
    main()
